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
        ('credit',        'ALTER TABLE users ADD COLUMN credit INTEGER DEFAULT 100'),   # 信用分
        ('age',           'ALTER TABLE users ADD COLUMN age INTEGER'),                  # 年龄
        ('gender',        'ALTER TABLE users ADD COLUMN gender TEXT'),                  # 性别
        ('interests',     'ALTER TABLE users ADD COLUMN interests TEXT'),               # 兴趣标签（逗号分隔）
        ('bio',           'ALTER TABLE users ADD COLUMN bio TEXT'),                     # 一句话介绍
        ('avatar',        'ALTER TABLE users ADD COLUMN avatar TEXT'),                  # 头像路径
        ('contact_public','ALTER TABLE users ADD COLUMN contact_public INTEGER DEFAULT 1'),  # 联系方式是否公开
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


# 全局变量：所有页面都能直接用 logged_in / nickname / avatar
@app.context_processor
def inject_global_vars():
    return {
        'logged_in': 'user_id' in session,
        'nickname': session.get('nickname', ''),
        'avatar': session.get('avatar', ''),
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
               u.nickname, u.age, u.credit, u.avatar,
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
    if request.method == 'POST':
        phone = request.form['phone'].strip()
        password = request.form['password']
        action = request.form['action']

        # 简单校验手机号格式
        if len(phone) != 11 or not phone.isdigit():
            return render_template('login.html', error='请输入11位手机号', action=action)

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
                return redirect(url_for('index'))
            except sqlite3.IntegrityError:
                conn.close()
                return render_template('login.html', error='该手机号已注册，请直接登录', action='register')
        else:
            # 登录
            c.execute('SELECT id, password_hash, nickname, avatar FROM users WHERE phone = ?', (phone,))
            user = c.fetchone()
            conn.close()
            if user and check_password_hash(user['password_hash'], password):
                session['user_id'] = user['id']
                session['nickname'] = user['nickname']
                session['avatar'] = user['avatar'] or ''
                return redirect(url_for('index'))
            else:
                return render_template('login.html', error='手机号或密码错误', action='login')

    return render_template('login.html', error='', action='login')


# 退出登录
@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('index'))


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
               u.bio, u.credit, u.avatar, u.contact_public
        FROM posts p JOIN users u ON p.user_id = u.id
        WHERE p.id = ? AND p.status = 1
    ''', (post_id,)).fetchone()

    if not post:
        conn.close()
        return '帖子不存在或已删除'

    comments = c.execute('''
        SELECT cm.id, cm.content, cm.create_time, u.nickname, u.id AS user_id, u.avatar
        FROM comments cm JOIN users u ON cm.user_id = u.id
        WHERE cm.post_id = ? ORDER BY cm.create_time ASC
    ''', (post_id,)).fetchall()

    like_count = c.execute('SELECT COUNT(*) AS n FROM likes WHERE post_id = ?', (post_id,)).fetchone()['n']
    fav_count = c.execute('SELECT COUNT(*) AS n FROM favorites WHERE post_id = ?', (post_id,)).fetchone()['n']

    liked = favorited = is_owner = blocked_by_author = False
    if 'user_id' in session:
        uid = session['user_id']
        liked = c.execute('SELECT 1 FROM likes WHERE post_id = ? AND user_id = ?',
                          (post_id, uid)).fetchone() is not None
        favorited = c.execute('SELECT 1 FROM favorites WHERE post_id = ? AND user_id = ?',
                              (post_id, uid)).fetchone() is not None
        is_owner = (uid == post['author_id'])
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
                           author_interests=author_interests,
                           contact_visible=contact_visible)


# 发表评论
@app.route('/post/<int:post_id>/comment', methods=['POST'])
def add_comment(post_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))

    content = request.form.get('content', '').strip()
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

    c.execute('INSERT INTO comments (post_id, user_id, content) VALUES (?, ?, ?)',
              (post_id, session['user_id'], content))
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


# 他人主页（看TA的资料和TA的帖子）
@app.route('/user/<int:user_id>')
def user_home(user_id):
    conn = get_conn()
    c = conn.cursor()
    user = c.execute('''SELECT id, nickname, age, gender, interests, bio, credit, avatar, create_time
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

    is_blocked = False
    if 'user_id' in session:
        is_blocked = c.execute('SELECT 1 FROM blacklist WHERE user_id = ? AND blocked_id = ?',
                               (session['user_id'], user_id)).fetchone() is not None
    conn.close()

    interests = parse_interests(user['interests'] or '')
    return render_template('user.html', user=user, posts=posts,
                           interests=interests, is_blocked=is_blocked,
                           is_self=(session.get('user_id') == user_id))


# 个人中心（资料 + 我的帖子 + 我收藏的帖子）
@app.route('/profile')
def profile():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    conn = get_conn()
    c = conn.cursor()
    user = c.execute('''SELECT id, nickname, age, gender, interests, bio, credit, avatar, contact_public
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
    conn.close()

    user_info = {
        'nickname': user['nickname'] or '',
        'age': user['age'],
        'gender': user['gender'] or '',
        'interests': parse_interests(user['interests'] or ''),
        'bio': user['bio'] or '',
        'credit': user['credit'],
        'avatar': user['avatar'] or '',
        'contact_public': user['contact_public'],
    }

    return render_template('profile.html', my_posts=my_posts,
                           fav_posts=fav_posts, user_info=user_info)


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


# 删除帖子（软删除）
@app.route('/post/<int:post_id>/delete', methods=['POST'])
def delete_post(post_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))

    conn = get_conn()
    conn.execute('UPDATE posts SET status = 0 WHERE id = ? AND user_id = ?',
                 (post_id, session['user_id']))
    conn.commit()
    conn.close()
    flash('帖子已删除')
    return redirect(url_for('profile'))


# 通知中心
@app.route('/notifications')
def notifications():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    conn = get_conn()
    notes = conn.execute('''
        SELECT n.id, n.type, n.content, n.create_time, n.post_id,
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
    app.run(debug=True, host='0.0.0.0', port=5000)
