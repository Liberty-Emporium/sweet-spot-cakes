"""
Comprehensive Audit & Geolocation System for Sweet Spot Cakes
- Tracks all logins, clock ins/outs, and system changes
- Captures geolocation from mobile QR scans
- Provides audit trail for compliance
"""

AUDIT_SCHEMA = """
-- Activity log for all system actions
CREATE TABLE IF NOT EXISTS activity_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    action_type TEXT NOT NULL,          -- 'login', 'logout', 'clock_in', 'clock_out', 
                                        -- 'employee_add', 'employee_edit', 'order_create', etc.
    user_id TEXT,                       -- Session user_id (emp_* or customer id)
    employee_id INTEGER REFERENCES employees(id),
    ip_address TEXT,
    user_agent TEXT,
    device_type TEXT,                   -- 'mobile', 'desktop', 'tablet', 'qr_kiosk'
    latitude REAL,
    longitude REAL,
    location_accuracy REAL,             -- GPS accuracy in meters
    details TEXT,                       -- JSON with action-specific data
    created_at TEXT DEFAULT (datetime('now'))
);

-- Index for common queries
CREATE INDEX IF NOT EXISTS idx_activity_user ON activity_logs(user_id, created_at);
CREATE INDEX IF NOT EXISTS idx_activity_type ON activity_logs(action_type, created_at);
CREATE INDEX IF NOT EXISTS idx_activity_employee ON activity_logs(employee_id, created_at);

-- Add geolocation to timesheets
ALTER TABLE timesheets ADD COLUMN latitude REAL;
ALTER TABLE timesheets ADD COLUMN longitude REAL;
ALTER TABLE timesheets ADD COLUMN location_accuracy REAL;
ALTER TABLE timesheets ADD COLUMN source TEXT DEFAULT 'web';  -- 'web', 'mobile', 'qr', 'manual'
"""

import json
import functools
from flask import request, session, g
from datetime import datetime

def log_action(action_type, employee_id=None, details=None):
    """Log an action to the activity log."""
    try:
        from app import get_db
        db = get_db()
        
        user_id = session.get('user_id') if session else None
        emp_id = employee_id if employee_id else session.get('employee_id') if session else None
        
        # Handle case where emp_id might be a string like 'emp_5'
        if isinstance(emp_id, str) and emp_id.startswith('emp_'):
            try:
                emp_id = int(emp_id.split('_')[1])
            except:
                emp_id = None
        
        ip = request.remote_addr if request else None
        ua = request.user_agent.string if request and request.user_agent else None
        
        # Detect device type
        device_type = 'unknown'
        if ua:
            ua_lower = ua.lower()
            if 'mobile' in ua_lower or 'android' in ua_lower or 'iphone' in ua_lower:
                device_type = 'mobile'
            elif 'tablet' in ua_lower or 'ipad' in ua_lower:
                device_type = 'tablet'
            else:
                device_type = 'desktop'
        
        # Check for QR/mobile indicators in request
        if request and request.headers.get('X-Source') in ['qr', 'mobile', 'kiosk']:
            device_type = request.headers.get('X-Source')
        
        details_json = json.dumps(details) if details else None
        
        db.execute("""
            INSERT INTO activity_logs 
            (action_type, user_id, employee_id, ip_address, user_agent, device_type, details)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (action_type, user_id, emp_id, ip, ua, device_type, details_json))
        db.commit()
    except Exception as e:
        # Silent fail - don't break the app if logging fails
        print(f"Audit logging error: {e}")

def audit_route(action_type, get_employee_id=None):
    """Decorator to automatically log route access."""
    def decorator(f):
        @functools.wraps(f)
        def wrapper(*args, **kwargs):
            result = f(*args, **kwargs)
            
            # Try to get employee_id
            emp_id = None
            if get_employee_id:
                try:
                    emp_id = get_employee_id(*args, **kwargs)
                except:
                    pass
            
            # Build details from request
            details = {
                'method': request.method if request else None,
                'endpoint': request.endpoint if request else None,
                'form_data': {k: v for k, v in request.form.items()} if request and request.form else None,
                'args': {k: v for k, v in request.args.items()} if request and request.args else None
            }
            
            log_action(action_type, emp_id, details)
            return result
        return wrapper
    return decorator

def log_clock_event(employee_id, event_type, latitude=None, longitude=None, accuracy=None, source='web'):
    """Log clock in/out with geolocation."""
    log_action(
        event_type,
        employee_id,
        {
            'latitude': latitude,
            'longitude': longitude,
            'accuracy': accuracy,
            'source': source,
            'timestamp': datetime.utcnow().isoformat()
        }
    )
