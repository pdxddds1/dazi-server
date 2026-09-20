# -*- coding: utf-8 -*-
"""
校园搭子APP - 后端主程序（Flask + SQLite）
启动方式：PyCharm 运行本文件，或命令行 python app.py
浏览器访问：http://127.0.0.1:5000
"""
from flask import (Flask, render_template, request, redirect, url_for,
                   session, flash, jsonify)
import sqlite3
from werkzeug.security import generate_password_hash, check_password_hash
import os
import uuid

app = Flask(__name__)
app.secret_key = 'dazi_app_secret_key_2026'  # 用于session加密，生产环境请改成随机字符串

# 编辑资料页里推荐点击的兴趣标签（用户也可以自己随便填）
SUGGEST_TAGS = ['运动', '篮球', '跑步', '健身', '阅读', '学习',
                '游戏', '电影', '音乐', '旅行', '美食', '摄影']

# 帖子分类
CATEGORIES = ['运动', '学习', '游戏', '生活', '其他']

# 数据库路径（和app.py在同一目录）
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'database.db')

# 头像上传相关
UPLOAD_FOLDER = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'static', 'uploads')
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp'}
MAX_AVATAR_SIZE = 2 * 1024 * 1024  # 2MB
os.makedirs(UPLOAD_FOLDER, exist_ok=True)  # 确保头像目录存在


# ==================== 数据库初始化 ====================
def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    # 用户表
    c.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            phone TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            nickname TEXT,
            create_time DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    # ===== 给users表补字段（老数据库升级不丢数据，缺哪列补哪列） =====
    c.execute("PRAGMA table_info(users)")
    columns = [row[1] for row in c.fetchall()]
    for col, sql in [
        ('credit',        'ALTER TABLE users ADD COLUMN credit INTEGER DEFAULT 100'),   # 信用分（旧，已不用）
        ('age',           'ALTER TABLE users ADD COLUMN age INTEGER'),                  # 年龄
        ('gender',        'ALTER TABLE users ADD COLUMN gender TEXT'),                  # 性别
        ('interests',     'ALTER TABLE users ADD COLUMN interests TEXT'),               # 兴趣标签（逗号分隔）
        ('bio',           'ALTER TABLE users ADD COLUMN bio TEXT'),                     # 一句话介绍
        ('avatar',        'ALTER TABLE users ADD COLUMN avatar TEXT'),                  # 头像路径
        ('contact_public','ALTER TABLE users ADD COLUMN contact_public INTEGER DEFAULT 1'),  # 联系方式是否公开
        ('level',         'ALTER TABLE users ADD COLUMN level INTEGER DEFAULT 1'),      # 等级
        ('exp',           'ALTER TABLE users ADD COLUMN exp INTEGER DEFAULT 0'),        # 经验值
        ('student_verified','ALTER TABLE users ADD COLUMN student_verified INTEGER DEFAULT 0'),  # 学生认证0未认证1已认证
        ('school',        'ALTER TABLE users ADD COLUMN school TEXT'),                  # 学校（公开）
        ('student_id',    'ALTER TABLE users ADD COLUMN student_id TEXT'),              # 学号（不公开）
        ('real_name',     'ALTER TABLE users ADD COLUMN real_name TEXT'),              # 真实姓名（不公开）
        ('last_active',   'ALTER TABLE users ADD COLUMN last_active DATETIME'),  # 最后活跃（NULL=从未活跃）
        ('show_online',   'ALTER TABLE users ADD COLUMN show_online INTEGER DEFAULT 1'),# 是否显示在线状态
        ('show_school',  'ALTER TABLE users ADD COLUMN show_school INTEGER DEFAULT 1'),# 是否公开学校
    ]:
        if col not in columns:
            c.execute(sql)
            print(f"✅ users表已增加{col}字段")
    # 帖子表
    c.execute('''
        CREATE TABLE IF NOT EXISTS posts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            title TEXT NOT NULL,
            category TEXT NOT NULL,
            content TEXT NOT NULL,
            contact TEXT NOT NULL,
            create_time DATETIME DEFAULT CURRENT_TIMESTAMP,
            status TINYINT DEFAULT 1,
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
    ''')
    # 评论表
    c.execute('''
        CREATE TABLE IF NOT EXISTS comments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            post_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            content TEXT NOT NULL,
            create_time DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    # 给comments表补 parent_id（楼中楼回复：NULL=一级评论，否则回复哪条评论）
    c.execute("PRAGMA table_info(comments)")
    comment_cols = [row[1] for row in c.fetchall()]
    if 'parent_id' not in comment_cols:
        c.execute('ALTER TABLE comments ADD COLUMN parent_id INTEGER')
        print("✅ comments表已增加parent_id字段（支持回复评论）")
    # 点赞表（同一个用户对同一帖子只能点一次赞）
    c.execute('''
        CREATE TABLE IF NOT EXISTS likes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            post_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            create_time DATETIME DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(post_id, user_id)
        )
    ''')
    # 收藏表
    c.execute('''
        CREATE TABLE IF NOT EXISTS favorites (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            post_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            create_time DATETIME DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(post_id, user_id)
        )
    ''')
    # 举报表
    c.execute('''
        CREATE TABLE IF NOT EXISTS reports (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            post_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            reason TEXT,
            create_time DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    # 黑名单表（user_id 拉黑了 blocked_id）
    c.execute('''
        CREATE TABLE IF NOT EXISTS blacklist (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            blocked_id INTEGER NOT NULL,
            create_time DATETIME DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(user_id, blocked_id)
        )
    ''')
    # 通知表（评论/点赞/收藏时给帖子作者发通知）
    c.execute('''
        CREATE TABLE IF NOT EXISTS notifications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,          -- 接收通知的人
            from_user_id INTEGER NOT NULL,     -- 触发通知的人
            post_id INTEGER,                   -- 关联的帖子
            type TEXT NOT NULL,                -- comment / like / favorite
            content TEXT,
            is_read INTEGER DEFAULT 0,         -- 0未读 1已读
            create_time DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    # 关注表（贴吧式：A关注B，B不需要同意，follower_id 是关注者）
    c.execute('''
        CREATE TABLE IF NOT EXISTS follows (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            follower_id INTEGER NOT NULL,      -- 关注者（谁点的关注）
            following_id INTEGER NOT NULL,     -- 被关注者
            create_time DATETIME DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(follower_id, following_id)
        )
    ''')
    # 消息表（好友聊天）
    c.execute('''
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            from_user_id INTEGER NOT NULL,     -- 发送者
            to_user_id INTEGER NOT NULL,       -- 接收者
            content TEXT,                      -- 文字内容
            msg_type TEXT DEFAULT 'text',     -- text / location
            location_lat REAL,                 -- 位置纬度（位置消息用）
            location_lng REAL,                 -- 位置经度
            is_read INTEGER DEFAULT 0,          -- 0未读 1已读
            create_time DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    # 公共聊天大厅消息表（所有人都能看）
    c.execute('''
        CREATE TABLE IF NOT EXISTS lobby_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            school TEXT,
            content TEXT NOT NULL,
            create_time DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    # 给老表补字段（msg_type/位置）
    c.execute("PRAGMA table_info(lobby_messages)")
    lobby_cols = [row[1] for row in c.fetchall()]
    if 'msg_type' not in lobby_cols:
        c.execute('ALTER TABLE lobby_messages ADD COLUMN msg_type TEXT DEFAULT "text"')
    if 'location_lat' not in lobby_cols:
        c.execute('ALTER TABLE lobby_messages ADD COLUMN location_lat REAL')
    if 'location_lng' not in lobby_cols:
        c.execute('ALTER TABLE lobby_messages ADD COLUMN location_lng REAL')
    if 'reply_to_id' not in lobby_cols:
        c.execute("ALTER TABLE lobby_messages ADD COLUMN reply_to_id INTEGER")
    if 'reply_to_nickname' not in lobby_cols:
        c.execute("ALTER TABLE lobby_messages ADD COLUMN reply_to_nickname TEXT")
    if 'reply_to_content' not in lobby_cols:
        c.execute("ALTER TABLE lobby_messages ADD COLUMN reply_to_content TEXT")
    conn.commit()
    conn.close()
    print("✅ 数据库初始化完成")


def get_conn():
    """获取数据库连接。返回的行既能用 cm['名字'] 也能用 cm[0] 取列"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def add_notification(conn, user_id, from_user_id, post_id, type_, content):
    """写一条通知（自己触发的不通知自己）。注意：conn 由调用方统一 commit"""
    if user_id == from_user_id:
        return
    conn.execute(
        'INSERT INTO notifications (user_id, from_user_id, post_id, type, content) VALUES (?, ?, ?, ?, ?)',
        (user_id, from_user_id, post_id, type_, content)
    )


def add_exp(conn, user_id, amount):
    """给用户加经验值，经验满自动升级。conn由调用方统一commit
    升级规则：每升一级需要 当前等级 × 100 经验（Lv1→Lv2要100，Lv2→Lv3要200...）"""
    user = conn.execute('SELECT level, exp FROM users WHERE id = ?', (user_id,)).fetchone()
    if not user:
        return 1, 0
    level = user['level']
    exp = user['exp'] + amount
    while exp >= level * 100:
        exp -= level * 100
        level += 1
    conn.execute('UPDATE users SET level = ?, exp = ? WHERE id = ?', (level, exp, user_id))
    return level, exp


def save_avatar(file_storage):
    """保存上传的头像，返回 (访问路径, 错误信息)。没传文件返回 (None, None)"""
    if not file_storage or not file_storage.filename:
        return None, None
    ext = file_storage.filename.rsplit('.', 1)[-1].lower() if '.' in file_storage.filename else ''
    if ext not in ALLOWED_EXTENSIONS:
        return None, '头像仅支持 png/jpg/jpeg/gif/webp 格式'
    file_storage.stream.seek(0, os.SEEK_END)
    size = file_storage.stream.tell()
    file_storage.stream.seek(0)
    if size > MAX_AVATAR_SIZE:
        return None, '头像图片不能超过2MB'
    filename = f'avatar_{uuid.uuid4().hex}.{ext}'
    file_storage.save(os.path.join(UPLOAD_FOLDER, filename))
    return f'/static/uploads/{filename}', None


def parse_interests(interests_raw):
    """把用户填的兴趣标签清洗成标准格式：中英文逗号都拆开→去空白→去重"""
    tags = [t.strip() for t in interests_raw.replace('，', ',').split(',') if t.strip()]
    return list(dict.fromkeys(tags))


def is_online(last_active):
    """5分钟内活跃=在线。last_active是数据库时间字符串"""
    if not last_active:
        return False
    from datetime import datetime, timedelta
    try:
        la = datetime.strptime(last_active[:19], '%Y-%m-%d %H:%M:%S')
        return datetime.now() - la < timedelta(minutes=5)
    except Exception:
        return False


# 每次请求自动更新当前用户的最后活跃时间（用于在线状态）
@app.before_request
def update_last_active():
    if 'user_id' in session:
        try:
            conn = get_conn()
            conn.execute('UPDATE users SET last_active = CURRENT_TIMESTAMP WHERE id = ?',
                         (session['user_id'],))
            conn.commit()
            conn.close()
        except Exception:
            pass


# 全局变量：所有页面都能直接用 logged_in / nickname / avatar
@app.context_processor
def inject_global_vars():
    # 未读消息数
    chat_unread = 0
    if 'user_id' in session:
        try:
            conn = get_conn()
            chat_unread = conn.execute(
                'SELECT COUNT(*) AS n FROM messages WHERE to_user_id=? AND is_read=0',
                (session['user_id'],)).fetchone()['n']
            conn.close()
        except Exception:
            pass
    return {
        'logged_in': 'user_id' in session,
        'nickname': session.get('nickname', ''),
        'avatar': session.get('avatar', ''),
        'chat_unread': chat_unread,
    }


# ==================== 页面路由 ====================

# 首页-帖子列表（支持分类筛选 + 关键词搜索 + 过滤被拉黑的人）
@app.route('/')
def index():
    category = request.args.get('category', '')
    q = request.args.get('q', '').strip()

    conn = get_conn()
    c = conn.cursor()

    sql = '''
        SELECT p.id, p.title, p.category, p.create_time,
               u.nickname, u.age, u.credit, u.avatar, u.student_verified,
               (SELECT COUNT(*) FROM likes l WHERE l.post_id = p.id) AS like_count
        FROM posts p JOIN users u ON p.user_id = u.id
        WHERE p.status = 1
    '''
    params = []
    if category and category != '全部':
        sql += ' AND p.category = ?'
        params.append(category)
    if q:
        sql += ' AND (p.title LIKE ? OR p.content LIKE ? OR p.category LIKE ?)'
        params += ['%' + q + '%', '%' + q + '%', '%' + q + '%']
    # 首页不显示"我拉黑的人"发的帖子
    if 'user_id' in session:
        blocked = [r['blocked_id'] for r in c.execute(
            'SELECT blocked_id FROM blacklist WHERE user_id = ?', (session['user_id'],))]
        if blocked:
            sql += ' AND p.user_id NOT IN (%s)' % ','.join('?' * len(blocked))
            params += blocked
    sql += ' ORDER BY p.create_time DESC'

    posts = c.execute(sql, params).fetchall()
    conn.close()

    return render_template('index.html', posts=posts,
                           categories=['全部'] + CATEGORIES,
                           current_cat=category or '全部', q=q)


# 登录注册页
@app.route('/login', methods=['GET', 'POST'])
def login():
    # 登录成功后跳回原页面（只允许站内路径，防钓鱼）
    next_page = (request.args.get('next') or request.form.get('next') or '').strip()
    if not next_page.startswith('/') or next_page.startswith('//'):
        next_page = ''

    if request.method == 'POST':
        phone = request.form['phone'].strip()
        password = request.form['password']
        action = request.form['action']

        # 简单校验手机号格式
        if len(phone) != 11 or not phone.isdigit():
            return render_template('login.html', error='请输入11位手机号', action=action, next=next_page)

        conn = get_conn()
        c = conn.cursor()

        if action == 'register':
            # 注册
            nickname = f'同学{phone[-4:]}'
            try:
                c.execute(
                    'INSERT INTO users (phone, password_hash, nickname) VALUES (?, ?, ?)',
                    (phone, generate_password_hash(password), nickname)
                )
                conn.commit()
                # 注册成功自动登录
                c.execute('SELECT id, nickname FROM users WHERE phone = ?', (phone,))
                user = c.fetchone()
                session['user_id'] = user[0]
                session['nickname'] = user[1]
                session['avatar'] = ''
                conn.close()
                return redirect(next_page or url_for('index'))
            except sqlite3.IntegrityError:
                conn.close()
                return render_template('login.html', error='该手机号已注册，请直接登录', action='register', next=next_page)
        else:
            # 登录
            c.execute('SELECT id, password_hash, nickname, avatar FROM users WHERE phone = ?', (phone,))
            user = c.fetchone()
            conn.close()
            if user and check_password_hash(user['password_hash'], password):
                session['user_id'] = user['id']
                session['nickname'] = user['nickname']
                session['avatar'] = user['avatar'] or ''
                return redirect(next_page or url_for('index'))
            else:
                return render_template('login.html', error='手机号或密码错误', action='login', next=next_page)

    # 已登录再访问登录页，直接跳首页（避免返回键卡在登录页）
    if 'user_id' in session:
        return redirect(next_page or url_for('index'))
    return render_template('login.html', error='', action='login', next=next_page)


# 退出登录
@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('index'))


# ==================== 学生实名认证 ====================
@app.route('/verify', methods=['GET', 'POST'])
def verify():
    if 'user_id' not in session:
        return redirect('/login?next=/verify')
    conn = get_conn()
    me = conn.execute('SELECT * FROM users WHERE id=?', (session['user_id'],)).fetchone()
    if request.method == 'POST':
        school = request.form['school'].strip()
        student_id = request.form['student_id'].strip()
        real_name = request.form['real_name'].strip()
        if not school or not student_id or not real_name:
            conn.close()
            return render_template('verify.html', me=me, error='请填写完整学校、学号、真实姓名')
        # MVP：提交即认证通过（真实项目应对接学校教务系统验证）
        conn.execute('''UPDATE users SET school=?, student_id=?, real_name=?, student_verified=1
                        WHERE id=?''',
                     (school, student_id, real_name, session['user_id']))
        conn.commit()
        conn.close()
        flash('✅ 学生认证成功！你的主页将显示"已学生认证"标识')
        return redirect('/profile')
    conn.close()
    return render_template('verify.html', me=me, error='')


# 切换"显示学校"开关
@app.route('/toggle_school', methods=['POST'])
def toggle_school():
    if 'user_id' not in session:
        return jsonify({'code': 1, 'message': '请先登录'})
    conn = get_conn()
    me = conn.execute('SELECT show_school FROM users WHERE id=?', (session['user_id'],)).fetchone()
    new_val = 0 if me['show_school'] else 1
    conn.execute('UPDATE users SET show_school=? WHERE id=?', (new_val, session['user_id']))
    conn.commit()
    conn.close()
    return jsonify({'code': 0, 'show_school': new_val})


# 切换"显示在线状态"开关
@app.route('/toggle_online', methods=['POST'])
def toggle_online():
    if 'user_id' not in session:
        return jsonify({'code': 1, 'message': '请先登录'})
    conn = get_conn()
    me = conn.execute('SELECT show_online FROM users WHERE id=?', (session['user_id'],)).fetchone()
    new_val = 0 if me['show_online'] else 1
    conn.execute('UPDATE users SET show_online=? WHERE id=?', (new_val, session['user_id']))
    conn.commit()
    conn.close()
    return jsonify({'code': 0, 'show_online': new_val})


# ==================== 好友聊天 ====================
# 聊天列表：和最近聊过天的人
@app.route('/messages')
def message_list():
    if 'user_id' not in session:
        return redirect('/login?next=/messages')
    uid = session['user_id']
    conn = get_conn()
    # 取每个聊天对象的最近一条消息
    rows = conn.execute('''
        SELECT u.id, u.nickname, u.avatar, u.student_verified, u.last_active, u.show_online,
               (SELECT content FROM messages m2 WHERE
                  ((m2.from_user_id=u.id AND m2.to_user_id=?) OR (m2.from_user_id=? AND m2.to_user_id=u.id))
                  ORDER BY m2.id DESC LIMIT 1) AS last_msg,
               (SELECT create_time FROM messages m3 WHERE
                  ((m3.from_user_id=u.id AND m3.to_user_id=?) OR (m3.from_user_id=? AND m3.to_user_id=u.id))
                  ORDER BY m3.id DESC LIMIT 1) AS last_time,
               (SELECT COUNT(*) FROM messages m4 WHERE m4.from_user_id=u.id AND m4.to_user_id=? AND m4.is_read=0) AS unread
        FROM messages m
        JOIN users u ON u.id = CASE WHEN m.from_user_id=? THEN m.to_user_id ELSE m.from_user_id END
        WHERE m.from_user_id=? OR m.to_user_id=?
        GROUP BY u.id
        ORDER BY MAX(m.id) DESC
    ''', (uid, uid, uid, uid, uid, uid, uid, uid)).fetchall()
    conn.close()
    return render_template('messages.html', chats=rows, is_online_fn=is_online)


# 聊天页
@app.route('/chat/<int:other_id>')
def chat_page(other_id):
    if 'user_id' not in session:
        return redirect('/login?next=/chat/%s' % other_id)
    uid = session['user_id']
    if uid == other_id:
        return redirect('/messages')
    conn = get_conn()
    other = conn.execute('SELECT id, nickname, avatar, student_verified, last_active, show_online FROM users WHERE id=?',
                         (other_id,)).fetchone()
    if not other:
        conn.close()
        flash('用户不存在')
        return redirect('/messages')
    # 拉黑检查：对方拉黑我 或 我拉黑对方 都不能聊
    blocked = conn.execute('''SELECT 1 FROM blacklist
                              WHERE (user_id=? AND blocked_id=?) OR (user_id=? AND blocked_id=?)''',
                           (other_id, uid, uid, other_id)).fetchone()
    if blocked:
        conn.close()
        flash('无法聊天：你们之间存在拉黑关系')
        return redirect('/messages')
    # 打开聊天页，把对方发给我的消息标记已读
    conn.execute('UPDATE messages SET is_read=1 WHERE from_user_id=? AND to_user_id=?', (other_id, uid))
    conn.commit()
    conn.close()
    return render_template('chat.html', other=other, is_online=is_online(other['last_active']) if other['show_online'] else False)


# 发消息（JSON接口）
@app.route('/chat/send', methods=['POST'])
def chat_send():
    if 'user_id' not in session:
        return jsonify({'code': 1, 'message': '请先登录'})
    uid = session['user_id']
    to_user_id = request.form.get('to_user_id', type=int)
    msg_type = request.form.get('msg_type', 'text')
    if not to_user_id:
        return jsonify({'code': 1, 'message': '参数错误'})
    conn = get_conn()
    # 拉黑检查
    blocked = conn.execute('''SELECT 1 FROM blacklist
                              WHERE (user_id=? AND blocked_id=?) OR (user_id=? AND blocked_id=?)''',
                           (to_user_id, uid, uid, to_user_id)).fetchone()
    if blocked:
        conn.close()
        return jsonify({'code': 1, 'message': '无法发送：你们之间存在拉黑关系'})
    if msg_type == 'location':
        lat = request.form.get('lat', type=float)
        lng = request.form.get('lng', type=float)
        if lat is None or lng is None:
            conn.close()
            return jsonify({'code': 1, 'message': '位置坐标缺失'})
        content = None
    else:
        content = request.form.get('content', '').strip()
        if not content:
            conn.close()
            return jsonify({'code': 1, 'message': '消息不能为空'})
        lat = lng = None
    cur = conn.execute('''INSERT INTO messages (from_user_id, to_user_id, content, msg_type, location_lat, location_lng)
                          VALUES (?, ?, ?, ?, ?, ?)''',
                       (uid, to_user_id, content, msg_type, lat, lng))
    conn.commit()
    msg_id = cur.lastrowid
    conn.close()
    return jsonify({'code': 0, 'id': msg_id})


# ==================== 公共聊天大厅 ====================
# 大厅页面
@app.route('/lobby')
def lobby():
    if 'user_id' not in session:
        return redirect('/login?next=/lobby')
    conn = get_conn()
    me = conn.execute('SELECT school, student_verified FROM users WHERE id=?',
                      (session['user_id'],)).fetchone()
    conn.close()
    return render_template('lobby.html', my_school=me['school'] or '',
                           verified=me['student_verified'])


# 大厅发消息
@app.route('/lobby/send', methods=['POST'])
def lobby_send():
    if 'user_id' not in session:
        return jsonify({'code': 1, 'message': '请先登录'})
    content = request.form.get('content', '').strip()
    msg_type = request.form.get('msg_type', 'text')
    if not content:
        return jsonify({'code': 1, 'message': '消息不能为空'})
    if len(content) > 200:
        return jsonify({'code': 1, 'message': '消息不能超过200字'})
    lat = request.form.get('lat', type=float)
    lng = request.form.get('lng', type=float)
    reply_id = request.form.get('reply_id', type=int)
    reply_nickname = None
    reply_content = None
    conn = get_conn()
    me = conn.execute('SELECT school FROM users WHERE id=?', (session['user_id'],)).fetchone()
    # 如果是回复，查被回复消息的昵称和内容快照
    if reply_id:
        src = conn.execute('''SELECT l.content, u.nickname FROM lobby_messages l
                              JOIN users u ON u.id=l.user_id WHERE l.id=?''', (reply_id,)).fetchone()
        if src:
            reply_nickname = src['nickname']
            reply_content = src['content']
    conn.execute('''INSERT INTO lobby_messages (user_id, school, content, msg_type,
                    location_lat, location_lng, reply_to_id, reply_to_nickname, reply_to_content)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                 (session['user_id'], me['school'], content, msg_type, lat, lng,
                  reply_id, reply_nickname, reply_content))
    conn.commit()
    conn.close()
    return jsonify({'code': 0})


# 大厅历史消息（scope=all 全部 / scope=school 本校）
@app.route('/lobby/history')
def lobby_history():
    if 'user_id' not in session:
        return jsonify({'code': 1, 'message': '请先登录'})
    scope = request.args.get('scope', 'all')
    after_id = request.args.get('after_id', 0, type=int)
    uid = session['user_id']
    conn = get_conn()
    if scope == 'school':
        me = conn.execute('SELECT school FROM users WHERE id=?', (uid,)).fetchone()
        if not me['school']:
            conn.close()
            return jsonify({'code': 2, 'message': '请先完成学生认证，才能看本校频道'})
        rows = conn.execute('''
            SELECT l.id, l.user_id, l.content, l.create_time, l.school,
                   l.msg_type, l.location_lat, l.location_lng,
                   l.reply_to_id, l.reply_to_nickname, l.reply_to_content,
                   u.nickname, u.avatar, u.level, u.student_verified, u.show_school
            FROM lobby_messages l JOIN users u ON u.id = l.user_id
            WHERE l.school = ? AND l.id > ?
            ORDER BY l.id ASC LIMIT 200
        ''', (me['school'], after_id)).fetchall()
    else:
        rows = conn.execute('''
            SELECT l.id, l.user_id, l.content, l.create_time, l.school,
                   l.msg_type, l.location_lat, l.location_lng,
                   l.reply_to_id, l.reply_to_nickname, l.reply_to_content,
                   u.nickname, u.avatar, u.level, u.student_verified, u.show_school
            FROM lobby_messages l JOIN users u ON u.id = l.user_id
            WHERE l.id > ?
            ORDER BY l.id ASC LIMIT 200
        ''', (after_id,)).fetchall()
    conn.close()
    msgs = []
    for r in rows:
        msgs.append({
            'id': r['id'],
            'user_id': r['user_id'],
            'mine': r['user_id'] == uid,
            'nickname': r['nickname'],
            'avatar': r['avatar'] or '',
            'level': r['level'],
            'verified': bool(r['student_verified']),
            'school': (r['school'] or '') if r['show_school'] else '',
            'content': r['content'],
            'msg_type': r['msg_type'] if 'msg_type' in r.keys() else 'text',
            'lat': r['location_lat'] if 'location_lat' in r.keys() else None,
            'lng': r['location_lng'] if 'location_lng' in r.keys() else None,
            'reply_to_id': r['reply_to_id'] if 'reply_to_id' in r.keys() else None,
            'reply_to_nickname': r['reply_to_nickname'] if 'reply_to_nickname' in r.keys() else None,
            'reply_to_content': r['reply_to_content'] if 'reply_to_content' in r.keys() else None,
            'time': r['create_time'][5:16] if r['create_time'] else '',
        })
    return jsonify({'code': 0, 'messages': msgs})


# 未读消息数（JSON）
@app.route('/chat/unread_count')
def chat_unread_count():
    if 'user_id' not in session:
        return jsonify({'code': 0, 'count': 0})
    conn = get_conn()
    n = conn.execute('SELECT COUNT(*) AS c FROM messages WHERE to_user_id=? AND is_read=0',
                     (session['user_id'],)).fetchone()['c']
    conn.close()
    return jsonify({'code': 0, 'count': n})


# 拉取和某人的聊天历史（JSON，轮询用）
@app.route('/chat/<int:other_id>/history')
def chat_history(other_id):
    if 'user_id' not in session:
        return jsonify({'code': 1, 'message': '请先登录'})
    uid = session['user_id']
    after_id = request.args.get('after_id', 0, type=int)
    conn = get_conn()
    rows = conn.execute('''SELECT m.id, m.from_user_id, m.content, m.msg_type, m.location_lat, m.location_lng,
                                  m.create_time, u.nickname, u.avatar
                           FROM messages m JOIN users u ON u.id = m.from_user_id
                           WHERE ((m.from_user_id=? AND m.to_user_id=?) OR (m.from_user_id=? AND m.to_user_id=?))
                             AND m.id > ?
                           ORDER BY m.id ASC''',
                        (uid, other_id, other_id, uid, after_id)).fetchall()
    # 把对方发给我的消息标记已读
    conn.execute('UPDATE messages SET is_read=1 WHERE from_user_id=? AND to_user_id=?', (other_id, uid))
    conn.commit()
    conn.close()
    msgs = []
    for r in rows:
        msgs.append({
            'id': r['id'],
            'mine': r['from_user_id'] == uid,
            'content': r['content'] or '',
            'msg_type': r['msg_type'],
            'lat': r['location_lat'],
            'lng': r['location_lng'],
            'time': r['create_time'][5:16] if r['create_time'] else '',
            'nickname': r['nickname'],
        })
    return jsonify({'code': 0, 'messages': msgs})


# 发布帖子
@app.route('/publish', methods=['GET', 'POST'])
def publish():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    if request.method == 'POST':
        title = request.form['title'].strip()
        category = request.form['category']
        content = request.form['content'].strip()
        contact = request.form['contact'].strip()

        # 后端校验（前端校验可以被绕过，后端必须再查一遍）
        if not all([title, category, content, contact]):
            return render_template('publish.html', error='请填写完整信息', categories=CATEGORIES)
        if len(title) < 2 or len(title) > 50:
            return render_template('publish.html', error='标题长度需在2-50字符之间', categories=CATEGORIES)
        if len(content) < 5 or len(content) > 500:
            return render_template('publish.html', error='内容长度需在5-500字符之间', categories=CATEGORIES)

        conn = get_conn()
        c = conn.cursor()
        c.execute(
            'INSERT INTO posts (user_id, title, category, content, contact) VALUES (?, ?, ?, ?, ?)',
            (session['user_id'], title, category, content, contact)
        )
        add_exp(conn, session['user_id'], 10)  # 发帖+10经验
        conn.commit()
        post_id = c.lastrowid
        conn.close()

        return redirect(url_for('post_detail', post_id=post_id))

    return render_template('publish.html', categories=CATEGORIES, error='')


# 帖子详情（作者资料 + 评论 + 点赞收藏 + 举报）
@app.route('/post/<int:post_id>')
def post_detail(post_id):
    conn = get_conn()
    c = conn.cursor()
    post = c.execute('''
        SELECT p.id, p.title, p.category, p.content, p.contact, p.create_time,
               u.nickname, u.id AS author_id, u.age, u.gender, u.interests,
               u.bio, u.credit, u.level, u.avatar, u.contact_public
        FROM posts p JOIN users u ON p.user_id = u.id
        WHERE p.id = ? AND p.status = 1
    ''', (post_id,)).fetchone()

    if not post:
        conn.close()
        return '帖子不存在或已删除'

    comments = c.execute('''
        SELECT cm.id, cm.content, cm.create_time, cm.parent_id,
               u.nickname, u.id AS user_id, u.avatar, u.level,
               ru.nickname AS reply_to_name
        FROM comments cm
        JOIN users u ON cm.user_id = u.id
        LEFT JOIN comments pc ON cm.parent_id = pc.id
        LEFT JOIN users ru ON pc.user_id = ru.id
        WHERE cm.post_id = ? ORDER BY cm.create_time ASC
    ''', (post_id,)).fetchall()

    like_count = c.execute('SELECT COUNT(*) AS n FROM likes WHERE post_id = ?', (post_id,)).fetchone()['n']
    fav_count = c.execute('SELECT COUNT(*) AS n FROM favorites WHERE post_id = ?', (post_id,)).fetchone()['n']

    liked = favorited = is_owner = blocked_by_author = is_following_author = False
    if 'user_id' in session:
        uid = session['user_id']
        liked = c.execute('SELECT 1 FROM likes WHERE post_id = ? AND user_id = ?',
                          (post_id, uid)).fetchone() is not None
        favorited = c.execute('SELECT 1 FROM favorites WHERE post_id = ? AND user_id = ?',
                              (post_id, uid)).fetchone() is not None
        is_owner = (uid == post['author_id'])
        # 是否已关注帖子作者
        is_following_author = c.execute('SELECT 1 FROM follows WHERE follower_id = ? AND following_id = ?',
                                        (uid, post['author_id'])).fetchone() is not None
        # 被帖子作者拉黑的话，不能评论
        blocked_by_author = c.execute('SELECT 1 FROM blacklist WHERE user_id = ? AND blocked_id = ?',
                                      (post['author_id'], uid)).fetchone() is not None
    conn.close()

    author_interests = parse_interests(post['interests'] or '')

    # 联系方式可见性：作者公开 或 当前是登录用户
    contact_visible = bool(post['contact_public']) or 'user_id' in session

    return render_template('detail.html', post=post, comments=comments,
                           like_count=like_count, fav_count=fav_count,
                           liked=liked, favorited=favorited,
                           is_owner=is_owner, blocked_by_author=blocked_by_author,
                           is_following_author=is_following_author,
                           author_interests=author_interests,
                           contact_visible=contact_visible)


# 发表评论
@app.route('/post/<int:post_id>/comment', methods=['POST'])
def add_comment(post_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))

    content = request.form.get('content', '').strip()
    parent_id = request.form.get('parent_id')
    parent_id = int(parent_id) if parent_id and parent_id.isdigit() else None
    conn = get_conn()
    c = conn.cursor()
    post = c.execute('SELECT id, user_id FROM posts WHERE id = ? AND status = 1', (post_id,)).fetchone()
    if not post:
        conn.close()
        return '帖子不存在或已删除'

    # 被作者拉黑的人不能评论
    if c.execute('SELECT 1 FROM blacklist WHERE user_id = ? AND blocked_id = ?',
                 (post['user_id'], session['user_id'])).fetchone():
        conn.close()
        flash('你已被该帖作者拉黑，无法评论')
        return redirect(url_for('post_detail', post_id=post_id))

    if not content:
        conn.close()
        flash('评论内容不能为空')
        return redirect(url_for('post_detail', post_id=post_id))
    if len(content) > 200:
        conn.close()
        flash('评论不能超过200个字符')
        return redirect(url_for('post_detail', post_id=post_id))

    c.execute('INSERT INTO comments (post_id, user_id, content, parent_id) VALUES (?, ?, ?, ?)',
              (post_id, session['user_id'], content, parent_id))
    add_exp(conn, session['user_id'], 2)  # 评论+2经验
    if parent_id:
        # 回复评论：通知被回复的人
        parent = c.execute('SELECT user_id FROM comments WHERE id = ? AND post_id = ?',
                           (parent_id, post_id)).fetchone()
        if parent:
            add_notification(conn, parent['user_id'], session['user_id'], post_id, 'comment',
                             f'{session["nickname"]} 回复了你：{content[:30]}')
    else:
        # 一级评论：通知帖子作者
        add_notification(conn, post['user_id'], session['user_id'], post_id, 'comment',
                         f'{session["nickname"]} 评论了你的帖子：{content[:30]}')
    conn.commit()
    conn.close()
    flash('评论成功')
    return redirect(url_for('post_detail', post_id=post_id))


# 点赞 / 取消点赞（返回JSON给前端按钮用）
@app.route('/post/<int:post_id>/like', methods=['POST'])
def toggle_like(post_id):
    if 'user_id' not in session:
        return jsonify({'code': 1, 'message': '请先登录'})
    conn = get_conn()
    c = conn.cursor()
    post = c.execute('SELECT id, user_id FROM posts WHERE id = ? AND status = 1', (post_id,)).fetchone()
    if not post:
        conn.close()
        return jsonify({'code': 1, 'message': '帖子不存在'})

    uid = session['user_id']
    liked = c.execute('SELECT 1 FROM likes WHERE post_id = ? AND user_id = ?', (post_id, uid)).fetchone()
    if liked:
        c.execute('DELETE FROM likes WHERE post_id = ? AND user_id = ?', (post_id, uid))
        liked = False
    else:
        c.execute('INSERT INTO likes (post_id, user_id) VALUES (?, ?)', (post_id, uid))
        liked = True
        add_notification(conn, post['user_id'], uid, post_id, 'like',
                         f'{session["nickname"]} 赞了你的帖子')
        add_exp(conn, post['user_id'], 2)  # 帖子被点赞，作者+2经验

    count = c.execute('SELECT COUNT(*) AS n FROM likes WHERE post_id = ?', (post_id,)).fetchone()['n']
    conn.commit()
    conn.close()
    return jsonify({'code': 0, 'liked': liked, 'count': count})


# 收藏 / 取消收藏（返回JSON）
@app.route('/post/<int:post_id>/favorite', methods=['POST'])
def toggle_favorite(post_id):
    if 'user_id' not in session:
        return jsonify({'code': 1, 'message': '请先登录'})
    conn = get_conn()
    c = conn.cursor()
    post = c.execute('SELECT id, user_id FROM posts WHERE id = ? AND status = 1', (post_id,)).fetchone()
    if not post:
        conn.close()
        return jsonify({'code': 1, 'message': '帖子不存在'})

    uid = session['user_id']
    fav = c.execute('SELECT 1 FROM favorites WHERE post_id = ? AND user_id = ?', (post_id, uid)).fetchone()
    if fav:
        c.execute('DELETE FROM favorites WHERE post_id = ? AND user_id = ?', (post_id, uid))
        favorited = False
    else:
        c.execute('INSERT INTO favorites (post_id, user_id) VALUES (?, ?)', (post_id, uid))
        favorited = True
        add_notification(conn, post['user_id'], uid, post_id, 'favorite',
                         f'{session["nickname"]} 收藏了你的帖子')

    count = c.execute('SELECT COUNT(*) AS n FROM favorites WHERE post_id = ?', (post_id,)).fetchone()['n']
    conn.commit()
    conn.close()
    return jsonify({'code': 0, 'favorited': favorited, 'count': count})


# 举报帖子
@app.route('/post/<int:post_id>/report', methods=['POST'])
def report_post(post_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))
    reason = request.form.get('reason', '').strip() or '无'
    conn = get_conn()
    conn.execute('INSERT INTO reports (post_id, user_id, reason) VALUES (?, ?, ?)',
                 (post_id, session['user_id'], reason))
    conn.commit()
    conn.close()
    flash('举报已提交，我们会尽快处理')
    return redirect(url_for('post_detail', post_id=post_id))


# 拉黑用户
@app.route('/user/<int:user_id>/block', methods=['POST'])
def block_user(user_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))
    if user_id == session['user_id']:
        flash('不能拉黑自己')
        return redirect(url_for('user_home', user_id=user_id))
    conn = get_conn()
    conn.execute('INSERT OR IGNORE INTO blacklist (user_id, blocked_id) VALUES (?, ?)',
                 (session['user_id'], user_id))
    conn.commit()
    conn.close()
    flash('已拉黑该用户，首页将不再显示TA的帖子')
    return redirect(url_for('user_home', user_id=user_id))


# 取消拉黑
@app.route('/user/<int:user_id>/unblock', methods=['POST'])
def unblock_user(user_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))
    conn = get_conn()
    conn.execute('DELETE FROM blacklist WHERE user_id = ? AND blocked_id = ?',
                 (session['user_id'], user_id))
    conn.commit()
    conn.close()
    flash('已取消拉黑')
    return redirect(url_for('user_home', user_id=user_id))


# ===== 关注 / 取消关注（贴吧式单向关注，返回JSON给按钮用）=====
@app.route('/user/<int:user_id>/follow', methods=['POST'])
def toggle_follow(user_id):
    if 'user_id' not in session:
        return jsonify({'code': 1, 'message': '请先登录'})
    if user_id == session['user_id']:
        return jsonify({'code': 1, 'message': '不能关注自己'})
    conn = get_conn()
    c = conn.cursor()
    target = c.execute('SELECT id FROM users WHERE id = ?', (user_id,)).fetchone()
    if not target:
        conn.close()
        return jsonify({'code': 1, 'message': '用户不存在'})

    uid = session['user_id']
    exists = c.execute('SELECT 1 FROM follows WHERE follower_id = ? AND following_id = ?',
                       (uid, user_id)).fetchone()
    if exists:
        c.execute('DELETE FROM follows WHERE follower_id = ? AND following_id = ?', (uid, user_id))
        following = False
    else:
        c.execute('INSERT INTO follows (follower_id, following_id) VALUES (?, ?)', (uid, user_id))
        following = True
        add_notification(conn, user_id, uid, None, 'follow', f'{session["nickname"]} 关注了你')
        add_exp(conn, user_id, 3)  # 被人关注，+3经验

    fan_count = c.execute('SELECT COUNT(*) AS n FROM follows WHERE following_id = ?',
                          (user_id,)).fetchone()['n']
    conn.commit()
    conn.close()
    return jsonify({'code': 0, 'following': following, 'count': fan_count})


# 我的关注 / 粉丝列表（贴吧风格，tab切换）
@app.route('/friends')
def friends():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    tab = request.args.get('tab', 'following')
    conn = get_conn()
    c = conn.cursor()

    if tab == 'fans':
        # 粉丝列表：谁关注了我
        users = c.execute('''
            SELECT u.id, u.nickname, u.avatar, u.credit, u.level, u.bio,
                   (SELECT COUNT(*) FROM follows f2 WHERE f2.following_id = u.id) AS fan_count,
                   (SELECT COUNT(*) FROM follows f3 WHERE f3.following_id = u.id AND f3.follower_id = ?) AS is_following
            FROM follows f JOIN users u ON f.follower_id = u.id
            WHERE f.following_id = ?
            ORDER BY f.create_time DESC
        ''', (session['user_id'], session['user_id'])).fetchall()
    elif tab == 'mutual':
        # 互相关注的好友：我关注了TA，TA也关注了我
        users = c.execute('''
            SELECT u.id, u.nickname, u.avatar, u.credit, u.level, u.bio,
                   (SELECT COUNT(*) FROM follows f2 WHERE f2.following_id = u.id) AS fan_count,
                   1 AS is_following
            FROM follows f JOIN users u ON f.following_id = u.id
            WHERE f.follower_id = ?
              AND EXISTS (SELECT 1 FROM follows f3 WHERE f3.follower_id = u.id AND f3.following_id = ?)
            ORDER BY f.create_time DESC
        ''', (session['user_id'], session['user_id'])).fetchall()
    else:
        # 关注列表：我关注了谁
        users = c.execute('''
            SELECT u.id, u.nickname, u.avatar, u.credit, u.level, u.bio,
                   (SELECT COUNT(*) FROM follows f2 WHERE f2.following_id = u.id) AS fan_count,
                   1 AS is_following
            FROM follows f JOIN users u ON f.following_id = u.id
            WHERE f.follower_id = ?
            ORDER BY f.create_time DESC
        ''', (session['user_id'],)).fetchall()

    my_fan_count = c.execute('SELECT COUNT(*) AS n FROM follows WHERE following_id = ?',
                             (session['user_id'],)).fetchone()['n']
    my_following_count = c.execute('SELECT COUNT(*) AS n FROM follows WHERE follower_id = ?',
                                   (session['user_id'],)).fetchone()['n']
    conn.close()

    return render_template('friends.html', users=users, tab=tab,
                           my_fan_count=my_fan_count, my_following_count=my_following_count)


# 我的拉黑名单（看我拉黑了谁，可解除）
@app.route('/blocklist')
def blocklist():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    conn = get_conn()
    users = conn.execute('''
        SELECT u.id, u.nickname, u.avatar, u.bio, u.level,
               (SELECT COUNT(*) FROM follows f WHERE f.following_id = u.id) AS fan_count
        FROM blacklist b JOIN users u ON b.blocked_id = u.id
        WHERE b.user_id = ? ORDER BY b.create_time DESC
    ''', (session['user_id'],)).fetchall()
    conn.close()
    return render_template('blocklist.html', users=users)


# 搜索用户（按昵称模糊搜索）
@app.route('/users')
def users():
    q = request.args.get('q', '').strip()
    conn = get_conn()
    c = conn.cursor()
    if q:
        users = c.execute('''
            SELECT u.id, u.nickname, u.avatar, u.credit, u.level, u.bio,
                   (SELECT COUNT(*) FROM follows f WHERE f.following_id = u.id) AS fan_count,
                   (SELECT COUNT(*) FROM follows f2 WHERE f2.following_id = u.id AND f2.follower_id = ?) AS is_following
            FROM users u
            WHERE u.nickname LIKE ?
            ORDER BY u.level DESC, u.id
            LIMIT 50
        ''', (session.get('user_id', 0), '%' + q + '%')).fetchall()
    else:
        users = []
    conn.close()
    return render_template('users.html', users=users, q=q)


# 他人主页（看TA的资料、关注/粉丝、TA的帖子）
@app.route('/user/<int:user_id>')
def user_home(user_id):
    conn = get_conn()
    c = conn.cursor()
    user = c.execute('''SELECT id, nickname, age, gender, interests, bio, credit, avatar, level, exp, create_time,
                               student_verified, school, show_online, show_school, last_active
                        FROM users WHERE id = ?''', (user_id,)).fetchone()
    if not user:
        conn.close()
        return '用户不存在'

    posts = c.execute('''
        SELECT p.id, p.title, p.category, p.create_time,
               (SELECT COUNT(*) FROM likes l WHERE l.post_id = p.id) AS like_count
        FROM posts p
        WHERE p.user_id = ? AND p.status = 1
        ORDER BY p.create_time DESC
    ''', (user_id,)).fetchall()

    # ===== 新增：关注数（TA关注了谁）、粉丝数（谁关注了TA）=====
    following_count = c.execute('SELECT COUNT(*) AS n FROM follows WHERE follower_id = ?',
                                (user_id,)).fetchone()['n']
    fan_count = c.execute('SELECT COUNT(*) AS n FROM follows WHERE following_id = ?',
                          (user_id,)).fetchone()['n']

    is_blocked = is_following = is_mutual = False
    if 'user_id' in session:
        is_blocked = c.execute('SELECT 1 FROM blacklist WHERE user_id = ? AND blocked_id = ?',
                               (session['user_id'], user_id)).fetchone() is not None
        # 当前登录用户是否关注了TA
        is_following = c.execute('SELECT 1 FROM follows WHERE follower_id = ? AND following_id = ?',
                                 (session['user_id'], user_id)).fetchone() is not None
        # TA是否也关注了我（互相关注=好友）
        ta_follows_me = c.execute('SELECT 1 FROM follows WHERE follower_id = ? AND following_id = ?',
                                   (user_id, session['user_id'])).fetchone() is not None
        is_mutual = is_following and ta_follows_me
    # 在线状态：对方开启了显示才算
    online_now = bool(user['show_online']) and is_online(user['last_active'])
    conn.close()

    interests = parse_interests(user['interests'] or '')
    return render_template('user.html', user=user, posts=posts,
                           interests=interests, is_blocked=is_blocked,
                           is_following=is_following, is_mutual=is_mutual,
                           online_now=online_now,
                           following_count=following_count, fan_count=fan_count,
                           is_self=(session.get('user_id') == user_id))


# 个人中心（资料 + 我的帖子 + 我收藏的帖子 + 关注/粉丝）
@app.route('/profile')
def profile():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    conn = get_conn()
    c = conn.cursor()
    user = c.execute('''SELECT id, nickname, age, gender, interests, bio, credit, avatar, level, exp, contact_public
                        FROM users WHERE id = ?''', (session['user_id'],)).fetchone()
    my_posts = c.execute('''
        SELECT id, title, category, create_time, status
        FROM posts WHERE user_id = ? ORDER BY create_time DESC
    ''', (session['user_id'],)).fetchall()
    fav_posts = c.execute('''
        SELECT p.id, p.title, p.category, p.create_time, u.nickname
        FROM favorites f
        JOIN posts p ON f.post_id = p.id
        JOIN users u ON p.user_id = u.id
        WHERE f.user_id = ? AND p.status = 1
        ORDER BY f.create_time DESC
    ''', (session['user_id'],)).fetchall()
    # ===== 新增：我的关注数 / 粉丝数 =====
    my_following_count = c.execute('SELECT COUNT(*) AS n FROM follows WHERE follower_id = ?',
                                   (session['user_id'],)).fetchone()['n']
    my_fan_count = c.execute('SELECT COUNT(*) AS n FROM follows WHERE following_id = ?',
                             (session['user_id'],)).fetchone()['n']
    conn.close()

    user_info = {
        'nickname': user['nickname'] or '',
        'age': user['age'],
        'gender': user['gender'] or '',
        'interests': parse_interests(user['interests'] or ''),
        'bio': user['bio'] or '',
        'credit': user['credit'],
        'level': user['level'],
        'exp': user['exp'],
        'avatar': user['avatar'] or '',
        'contact_public': user['contact_public'],
    }

    return render_template('profile.html', my_posts=my_posts,
                           fav_posts=fav_posts, user_info=user_info,
                           my_following_count=my_following_count,
                           my_fan_count=my_fan_count)


# 编辑个人资料（含头像上传、联系方式是否公开）
@app.route('/profile/edit', methods=['GET', 'POST'])
def edit_profile():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    conn = get_conn()
    c = conn.cursor()

    if request.method == 'POST':
        nickname = request.form['nickname'].strip()
        age = request.form['age'].strip()
        gender = request.form['gender'].strip()
        interests_raw = request.form['interests'].strip()
        bio = request.form['bio'].strip()
        contact_public = 1 if request.form.get('contact_public') else 0
        avatar_file = request.files.get('avatar')
        new_avatar, avatar_error = save_avatar(avatar_file)

        # ===== 后端校验 =====
        error = None
        if not nickname:
            error = '昵称不能为空'
        elif len(nickname) > 20:
            error = '昵称长度不能超过20个字符'
        elif age and (not age.isdigit() or not (10 <= int(age) <= 100)):
            error = '年龄请输入10-100之间的数字'
        elif len(bio) > 100:
            error = '自我介绍不能超过100个字符'
        elif avatar_error:
            error = avatar_error

        if error:
            conn.close()
            return render_template('edit_profile.html', error=error,
                                   nickname=nickname, age=age, gender=gender,
                                   interests=interests_raw, bio=bio,
                                   contact_public=contact_public,
                                   avatar=session.get('avatar', ''),
                                   suggest_tags=SUGGEST_TAGS)

        # 兴趣标签清洗后存成 "运动,阅读,游戏"
        interests_str = ','.join(parse_interests(interests_raw))

        c.execute('''UPDATE users SET nickname = ?, age = ?, gender = ?, interests = ?, bio = ?,
                     avatar = COALESCE(?, avatar), contact_public = ?
                     WHERE id = ?''',
                  (nickname, int(age) if age else None, gender,
                   interests_str, bio, new_avatar, contact_public, session['user_id']))
        conn.commit()
        conn.close()

        # 同步更新session里显示用的昵称和头像
        session['nickname'] = nickname
        if new_avatar:
            session['avatar'] = new_avatar
        flash('资料保存成功')
        return redirect(url_for('profile'))

    # GET：把已保存的资料查出来回填到表单
    user = c.execute('SELECT nickname, age, gender, interests, bio, avatar, contact_public '
                     'FROM users WHERE id = ?', (session['user_id'],)).fetchone()
    conn.close()

    return render_template('edit_profile.html', error='',
                           nickname=user['nickname'] or '', age=user['age'] or '',
                           gender=user['gender'] or '', interests=user['interests'] or '',
                           bio=user['bio'] or '', contact_public=user['contact_public'],
                           avatar=user['avatar'] or '', suggest_tags=SUGGEST_TAGS)


# 修改密码
@app.route('/change_password', methods=['GET', 'POST'])
def change_password():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    error = ''
    if request.method == 'POST':
        old_pw = request.form['old_password']
        new_pw = request.form['new_password']
        confirm_pw = request.form['confirm_password']

        conn = get_conn()
        user = conn.execute('SELECT password_hash FROM users WHERE id = ?',
                            (session['user_id'],)).fetchone()
        conn.close()

        if not user or not check_password_hash(user['password_hash'], old_pw):
            error = '旧密码不正确'
        elif len(new_pw) < 6:
            error = '新密码至少6位'
        elif new_pw != confirm_pw:
            error = '两次输入的新密码不一致'
        else:
            conn = get_conn()
            conn.execute('UPDATE users SET password_hash = ? WHERE id = ?',
                         (generate_password_hash(new_pw), session['user_id']))
            conn.commit()
            conn.close()
            flash('密码修改成功，下次请用新密码登录')
            return redirect(url_for('profile'))

    return render_template('change_password.html', error=error)


# 编辑帖子（只有作者能编辑）
@app.route('/post/<int:post_id>/edit', methods=['GET', 'POST'])
def edit_post(post_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))

    conn = get_conn()
    c = conn.cursor()
    post = c.execute('SELECT * FROM posts WHERE id = ? AND user_id = ?',
                     (post_id, session['user_id'])).fetchone()
    if not post:
        conn.close()
        return '帖子不存在或无权编辑'

    if request.method == 'POST':
        title = request.form['title'].strip()
        category = request.form['category']
        content = request.form['content'].strip()
        contact = request.form['contact'].strip()

        if not all([title, category, content, contact]):
            return render_template('edit_post.html', post=post, error='请填写完整信息',
                                   categories=CATEGORIES)
        if len(title) < 2 or len(title) > 50:
            return render_template('edit_post.html', post=post, error='标题长度需在2-50字符之间',
                                   categories=CATEGORIES)
        if len(content) < 5 or len(content) > 500:
            return render_template('edit_post.html', post=post, error='内容长度需在5-500字符之间',
                                   categories=CATEGORIES)

        c.execute('''UPDATE posts SET title = ?, category = ?, content = ?, contact = ?
                     WHERE id = ? AND user_id = ?''',
                  (title, category, content, contact, post_id, session['user_id']))
        conn.commit()
        conn.close()
        flash('帖子已更新')
        return redirect(url_for('post_detail', post_id=post_id))

    conn.close()
    return render_template('edit_post.html', post=post, error='', categories=CATEGORIES)


# 删除帖子（软删除）：作者本人 或 管理员(id=1)
@app.route('/post/<int:post_id>/delete', methods=['POST'])
def delete_post(post_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))
    uid = session['user_id']
    is_admin = (uid == 2)  # 只有 id=2 (同学7246) 是管理员
    conn = get_conn()
    if is_admin:
        conn.execute('UPDATE posts SET status = 0 WHERE id = ?', (post_id,))
        flash('管理员：帖子已删除')
    else:
        conn.execute('UPDATE posts SET status = 0 WHERE id = ? AND user_id = ?',
                     (post_id, uid))
        flash('帖子已删除')
    conn.commit()
    conn.close()
    # 管理员删完回首页，作者删完回个人中心
    if is_admin:
        return redirect('/')
    return redirect(url_for('profile'))


# 通知中心
@app.route('/notifications')
def notifications():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    conn = get_conn()
    notes = conn.execute('''
        SELECT n.id, n.type, n.content, n.create_time, n.post_id,
               n.from_user_id,
               u.nickname AS from_name, u.avatar AS from_avatar
        FROM notifications n JOIN users u ON n.from_user_id = u.id
        WHERE n.user_id = ?
        ORDER BY n.create_time DESC LIMIT 100
    ''', (session['user_id'],)).fetchall()
    # 打开通知页就全部标记已读
    conn.execute('UPDATE notifications SET is_read = 1 WHERE user_id = ? AND is_read = 0',
                 (session['user_id'],))
    conn.commit()
    conn.close()
    return render_template('notifications.html', notes=notes)


# 未读通知数（顶部导航小红点用）
@app.route('/api/unread_count')
def api_unread_count():
    if 'user_id' not in session:
        return jsonify({'count': 0})
    conn = get_conn()
    n = conn.execute('SELECT COUNT(*) AS n FROM notifications '
                     'WHERE user_id = ? AND is_read = 0', (session['user_id'],)).fetchone()['n']
    conn.close()
    return jsonify({'count': n})


# ==================== 启动 ====================
if __name__ == '__main__':
    init_db()
    print("🚀 校园搭子APP启动成功！")
    print("📱 请在浏览器打开: http://127.0.0.1:5000")
    # threaded=True：多线程，聊天页轮询时其他按钮也不会卡住
    # debug=False：公网暴露必须关debug（否则别人能通过调试器控制你电脑）
    # threaded=True：多线程，聊天页轮询时其他按钮也不会卡住
    app.run(debug=False, host='0.0.0.0', port=5000, threaded=True)
