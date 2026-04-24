import re
from typing import List
from werkzeug.utils import secure_filename

class Validators:
    """Collection of validation utilities"""
    
    @staticmethod
    def validate_email(email: str) -> bool:
        """Validate email format"""
        pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
        return bool(re.match(pattern, email))
    
    @staticmethod
    def validate_msu_email(email: str) -> bool:
        """Validate MSU email address"""
        allowed_domains = ['msu.ac.zw', 'staff.msu.ac.zw', 'students.msu.ac.zw']
        domain = email.split('@')[-1]
        return domain in allowed_domains
    
    @staticmethod
    def validate_student_id(student_id: str) -> bool:
        """Validate MSU student ID format (e.g., MSU12345)"""
        pattern = r'^MSU\d{5,6}$'
        return bool(re.match(pattern, student_id))
    
    @staticmethod
    def validate_video_title(title: str) -> bool:
        """Validate video title"""
        if not title or len(title) < 3 or len(title) > 255:
            return False
        # Check for profanity (simplified)
        profanity_words = ['badword1', 'badword2']  # Add actual profanity list
        title_lower = title.lower()
        return not any(word in title_lower for word in profanity_words)
    
    @staticmethod
    def sanitize_filename(filename: str) -> str:
        """Sanitize filename to prevent path traversal attacks"""
        return secure_filename(filename)
    
    @staticmethod
    def validate_file_size(file_size: int, max_size: int = 100 * 1024 * 1024) -> bool:
        """Validate file size doesn't exceed limit"""
        return file_size <= max_size
    
    @staticmethod
    def validate_video_extension(filename: str, allowed_extensions: List[str]) -> bool:
        """Validate video file extension"""
        extension = filename.split('.')[-1].lower()
        return extension in allowed_extensions
    
    @staticmethod
    def validate_password_strength(password: str) -> dict:
        """Check password strength and return validation result"""
        strength = {
            'is_valid': True,
            'score': 0,
            'feedback': []
        }
        
        if len(password) < 8:
            strength['is_valid'] = False
            strength['feedback'].append('Password must be at least 8 characters long')
        else:
            strength['score'] += 1
        
        if not re.search(r'[A-Z]', password):
            strength['feedback'].append('Password should contain at least one uppercase letter')
        else:
            strength['score'] += 1
        
        if not re.search(r'[a-z]', password):
            strength['feedback'].append('Password should contain at least one lowercase letter')
        else:
            strength['score'] += 1
        
        if not re.search(r'\d', password):
            strength['feedback'].append('Password should contain at least one number')
        else:
            strength['score'] += 1
        
        if not re.search(r'[!@#$%^&*(),.?":{}|<>]', password):
            strength['feedback'].append('Password should contain at least one special character')
        else:
            strength['score'] += 1
        
        strength['strength_level'] = ['Very Weak', 'Weak', 'Moderate', 'Strong', 'Very Strong'][strength['score'] - 1] if strength['score'] > 0 else 'Very Weak'
        
        return strength
    
    @staticmethod
    def validate_course_code(course_code: str) -> bool:
        """Validate course code format (e.g., CS101, MATH202)"""
        pattern = r'^[A-Z]{2,4}\d{3,4}$'
        return bool(re.match(pattern, course_code))
    
    @staticmethod
    def sanitize_html(content: str) -> str:
        """Basic HTML sanitization to prevent XSS"""
        import html
        return html.escape(content)
    
    @staticmethod
    def validate_comment_content(content: str) -> bool:
        """Validate comment content"""
        if not content or len(content) > 1000:
            return False
        return True