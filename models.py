from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
import json

db = SQLAlchemy()

class Cookie(db.Model):
    """Instagram çerezlerini saklayan model"""
    __tablename__ = 'cookies'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True, nullable=False)
    value = db.Column(db.Text, nullable=False)
    domain = db.Column(db.String(100))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    def __repr__(self):
        return f'<Cookie {self.name}>'

class BearerToken(db.Model):
    """Instagram Mobile API Bearer Token saklayan model - Her hesap kendi device bilgilerini taşır"""
    __tablename__ = 'bearer_tokens'
    
    id = db.Column(db.Integer, primary_key=True)
    account_label = db.Column(db.String(200))  # Hesap etiketi (örn: "Ana Hesap", "İş Hesabı")
    is_active = db.Column(db.Boolean, default=False)  # Aktif hesap
    
    # API Kimlik Bilgileri
    token = db.Column(db.Text, nullable=False)
    username = db.Column(db.String(100))
    user_id = db.Column(db.String(100))
    password = db.Column(db.String(200))  # Hesap şifresi (opsiyonel)
    
    # Her hesaba özel device bilgileri - KRİTİK
    device_id = db.Column(db.String(200))  # X-IG-Device-ID
    android_id = db.Column(db.String(200))  # X-IG-Android-ID
    user_agent = db.Column(db.Text)  # User-Agent header
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    def __repr__(self):
        label = self.account_label or self.username or 'Unknown'
        return f'<BearerToken {label}>'

class Group(db.Model):
    """Instagram gruplarını saklayan model"""
    __tablename__ = 'groups'
    
    id = db.Column(db.Integer, primary_key=True)
    thread_id = db.Column(db.String(200), unique=True, nullable=False)
    title = db.Column(db.String(500))
    user_count = db.Column(db.Integer, default=0)
    last_checked = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # İlişkiler
    users = db.relationship('GroupUser', back_populates='group', cascade='all, delete-orphan')
    messages = db.relationship('Message', back_populates='group', cascade='all, delete-orphan')
    weekly_activities = db.relationship('WeeklyActivity', back_populates='group', cascade='all, delete-orphan')
    
    def __repr__(self):
        return f'<Group {self.title}>'

class User(db.Model):
    """Instagram kullanıcılarını saklayan model"""
    __tablename__ = 'users'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.String(100), unique=True, nullable=False)
    username = db.Column(db.String(100))
    full_name = db.Column(db.String(200))
    profile_pic_url = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # İlişkiler
    groups = db.relationship('GroupUser', back_populates='user')
    messages = db.relationship('Message', back_populates='user')
    media_shares = db.relationship('MediaShare', back_populates='user')
    weekly_activities = db.relationship('WeeklyActivity', back_populates='user')
    
    def __repr__(self):
        return f'<User {self.username}>'

class GroupUser(db.Model):
    """Grup-kullanıcı ilişkisini saklayan model (Many-to-Many)"""
    __tablename__ = 'group_users'
    
    id = db.Column(db.Integer, primary_key=True)
    group_id = db.Column(db.Integer, db.ForeignKey('groups.id', ondelete='CASCADE'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    joined_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # İlişkiler
    group = db.relationship('Group', back_populates='users')
    user = db.relationship('User', back_populates='groups')
    
    __table_args__ = (
        db.UniqueConstraint('group_id', 'user_id', name='unique_group_user'),
    )

class Message(db.Model):
    """Mesajları saklayan model"""
    __tablename__ = 'messages'
    
    id = db.Column(db.Integer, primary_key=True)
    message_id = db.Column(db.String(200), unique=True, nullable=False)
    group_id = db.Column(db.Integer, db.ForeignKey('groups.id', ondelete='CASCADE'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='SET NULL'))
    item_type = db.Column(db.String(50))  # text, media_share, etc.
    text = db.Column(db.Text)
    timestamp = db.Column(db.BigInteger)  # Instagram timestamp
    message_date = db.Column(db.DateTime)
    raw_data = db.Column(db.Text)  # JSON olarak tüm mesaj verisi
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # İlişkiler
    group = db.relationship('Group', back_populates='messages')
    user = db.relationship('User', back_populates='messages')
    media_share = db.relationship('MediaShare', back_populates='message', uselist=False, cascade='all, delete-orphan')
    
    def __repr__(self):
        return f'<Message {self.message_id}>'

class MediaShare(db.Model):
    """Medya paylaşımlarını saklayan model"""
    __tablename__ = 'media_shares'
    
    id = db.Column(db.Integer, primary_key=True)
    message_id = db.Column(db.Integer, db.ForeignKey('messages.id', ondelete='CASCADE'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='SET NULL'))
    media_id = db.Column(db.String(200))
    media_type = db.Column(db.String(50))  # reel, post, story
    media_code = db.Column(db.String(100))
    media_url = db.Column(db.Text)
    thumbnail_url = db.Column(db.Text)
    owner_username = db.Column(db.String(100))
    caption = db.Column(db.Text)
    like_count = db.Column(db.Integer, default=0)
    comment_count = db.Column(db.Integer, default=0)
    share_date = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # İlişkiler
    message = db.relationship('Message', back_populates='media_share')
    user = db.relationship('User', back_populates='media_shares')
    
    def __repr__(self):
        return f'<MediaShare {self.media_code}>'

class WeeklyActivity(db.Model):
    """Haftalık aktivite istatistiklerini saklayan model"""
    __tablename__ = 'weekly_activities'
    
    id = db.Column(db.Integer, primary_key=True)
    group_id = db.Column(db.Integer, db.ForeignKey('groups.id', ondelete='CASCADE'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    week_start = db.Column(db.Date, nullable=False)
    week_end = db.Column(db.Date, nullable=False)
    message_count = db.Column(db.Integer, default=0)
    media_share_count = db.Column(db.Integer, default=0)
    reel_count = db.Column(db.Integer, default=0)
    post_count = db.Column(db.Integer, default=0)
    story_count = db.Column(db.Integer, default=0)
    total_likes = db.Column(db.Integer, default=0)
    total_comments = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # İlişkiler
    group = db.relationship('Group', back_populates='weekly_activities')
    user = db.relationship('User', back_populates='weekly_activities')
    
    __table_args__ = (
        db.UniqueConstraint('group_id', 'user_id', 'week_start', name='unique_weekly_activity'),
    )
    
    def __repr__(self):
        return f'<WeeklyActivity {self.user_id} - {self.week_start}>'

class SystemLog(db.Model):
    """Sistem loglarını saklayan model"""
    __tablename__ = 'system_logs'
    
    id = db.Column(db.Integer, primary_key=True)
    action = db.Column(db.String(100))
    details = db.Column(db.Text)
    status = db.Column(db.String(50))
    error_message = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    def __repr__(self):
        return f'<SystemLog {self.action} - {self.created_at}>'
