from flask import Flask, render_template, request, redirect, url_for, session
import sqlite3
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime
import os

app = Flask(__name__)
app.secret_key = 'dazi_app_secret_key_2026'  # 用于session加密，生产环境请改成随机字符串

# 编辑资料页里推荐点击的兴趣标签（用户也可以自己随便填）
SUGGEST_TAGS = ['运动', '篮球', '跑步', '健身', '阅读', '学习',
                '游戏', '电影', '音乐', '旅行', '美食', '摄影']

# 数据库路径（和app.py在同一目录）
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'database.db')

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
    # ===== 新增：给users表加"信用分"字段 =====
    c.execute("PRAGMA table_info(users)")   # 查看users表现在有哪些列
    columns = [row[1] for row in c.fetchall()]
    if 'credit' not in columns:             # 如果还没有credit列
        c.execute("ALTER TABLE users ADD COLUMN credit INTEGER DEFAULT 100")
        print("✅ users表已增加信用分字段")
    # ===== 新增：给users表加"个人资料"字段（年龄/性别/兴趣标签/自我介绍） =====
    # 思路和上面加credit一样：先看有哪些列，缺哪列就补哪列（老数据库升级不丢数据）
    c.execute("PRAGMA table_info(users)")
    columns = [row[1] for row in c.fetchall()]
    for col, sql in [
        ('age',       'ALTER TABLE users ADD COLUMN age INTEGER'),      # 年龄
        ('gender',    'ALTER TABLE users ADD COLUMN gender TEXT'),      # 性别：男/女（空=保密）
        ('interests', 'ALTER TABLE users ADD COLUMN interests TEXT'),   # 兴趣标签（逗号分隔，如：运动,阅读,游戏）
        ('bio',       'ALTER TABLE users ADD COLUMN bio TEXT'),         # 一句话自我介绍
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
    conn.commit()
    conn.close()
    print("✅ 数据库初始化完成")

# ==================== 路由 ====================

# 首页-帖子列表
@app.route('/')
def index():
    category = request.args.get('category', '')
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    if category and category != '全部':
        c.execute('''
            SELECT p.id, p.title, p.category, p.create_time, u.nickname
            FROM posts p JOIN users u ON p.user_id = u.id
            WHERE p.status = 1 AND p.category = ?
            ORDER BY p.create_time DESC
        ''', (category,))
    else:
        c.execute('''
            SELECT p.id, p.title, p.category, p.create_time, u.nickname
            FROM posts p JOIN users u ON p.user_id = u.id
            WHERE p.status = 1
            ORDER BY p.create_time DESC
        ''')

    posts = c.fetchall()
    conn.close()

    categories = ['全部', '运动', '学习', '游戏', '生活', '其他']
    return render_template('index.html', posts=posts, categories=categories,
                           current_cat=category or '全部',
                           logged_in='user_id' in session,
                           nickname=session.get('nickname', ''))

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

        conn = sqlite3.connect(DB_PATH)
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
                conn.close()
                return redirect(url_for('index'))
            except sqlite3.IntegrityError:
                conn.close()
                return render_template('login.html', error='该手机号已注册，请直接登录', action='register')
        else:
            # 登录
            c.execute('SELECT id, password_hash, nickname FROM users WHERE phone = ?', (phone,))
            user = c.fetchone()
            conn.close()
            if user and check_password_hash(user[1], password):
                session['user_id'] = user[0]
                session['nickname'] = user[2]
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

        # 后端校验（对应PRD业务规则）
        if not all([title, category, content, contact]):
            return render_template('publish.html', error='请填写完整信息', categories=['运动','学习','游戏','生活','其他'])
        if len(title) < 2 or len(title) > 50:
            return render_template('publish.html', error='标题长度需在2-50字符之间', categories=['运动','学习','游戏','生活','其他'])
        if len(content) < 5 or len(content) > 500:
            return render_template('publish.html', error='内容长度需在5-500字符之间', categories=['运动','学习','游戏','生活','其他'])

        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute(
            'INSERT INTO posts (user_id, title, category, content, contact) VALUES (?, ?, ?, ?, ?)',
            (session['user_id'], title, category, content, contact)
        )
        conn.commit()
        post_id = c.lastrowid
        conn.close()

        return redirect(url_for('post_detail', post_id=post_id))

    categories = ['运动', '学习', '游戏', '生活', '其他']
    return render_template('publish.html', categories=categories, error='')

# 帖子详情
@app.route('/post/<int:post_id>')
def post_detail(post_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''
        SELECT p.id, p.title, p.category, p.content, p.contact, p.create_time, u.nickname
        FROM posts p JOIN users u ON p.user_id = u.id
        WHERE p.id = ? AND p.status = 1
    ''', (post_id,))
    post = c.fetchone()
    conn.close()

    if not post:
        return '帖子不存在或已删除'
    return render_template('detail.html', post=post,
                           logged_in='user_id' in session,
                           is_owner=(session.get('user_id') == post_id) if 'user_id' in session else False)

# 个人中心
@app.route('/profile')
def profile():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    # 查询当前用户的个人资料（含新增的年龄/性别/兴趣标签/介绍）
    c.execute('SELECT id, nickname, age, gender, interests, bio FROM users WHERE id = ?',
              (session['user_id'],))
    user = c.fetchone()
    c.execute('''
        SELECT id, title, category, create_time, status
        FROM posts
        WHERE user_id = ?
        ORDER BY create_time DESC
    ''', (session['user_id'],))
    my_posts = c.fetchall()
    conn.close()

    # 把逗号分隔的兴趣标签拆成列表，方便模板里逐个显示成小徽章
    interests = []
    if user and user[4]:
        interests = [t.strip() for t in user[4].split(',') if t.strip()]

    # 整理成字典传给页面，模板里写 user_info.xxx 比写 user[2] 好懂
    user_info = {
        'nickname': user[1] if user else session.get('nickname', ''),
        'age': user[2] if user else None,
        'gender': user[3] if user else '',
        'interests': interests,
        'bio': user[5] if user else '',
    }

    return render_template('profile.html', my_posts=my_posts, user_info=user_info)


# 编辑个人资料（昵称/年龄/性别/兴趣标签/自我介绍）
@app.route('/profile/edit', methods=['GET', 'POST'])
def edit_profile():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    if request.method == 'POST':
        nickname = request.form['nickname'].strip()
        age = request.form['age'].strip()
        gender = request.form['gender'].strip()
        interests_raw = request.form['interests'].strip()
        bio = request.form['bio'].strip()

        # ===== 后端校验（前端校验可以被绕过，后端必须再查一遍） =====
        error = None
        if not nickname:
            error = '昵称不能为空'
        elif len(nickname) > 20:
            error = '昵称长度不能超过20个字符'
        elif age and (not age.isdigit() or not (10 <= int(age) <= 100)):
            error = '年龄请输入10-100之间的数字'
        elif len(bio) > 100:
            error = '自我介绍不能超过100个字符'

        if error:
            conn.close()
            return render_template('edit_profile.html', error=error,
                                   nickname=nickname, age=age, gender=gender,
                                   interests=interests_raw, bio=bio,
                                   suggest_tags=SUGGEST_TAGS)

        # 兴趣标签：中英文逗号都拆开 → 去掉空白 → 去重，存成 "运动,阅读,游戏"
        tags = [t.strip() for t in interests_raw.replace('，', ',').split(',') if t.strip()]
        tags = list(dict.fromkeys(tags))
        interests_str = ','.join(tags)

        c.execute('''UPDATE users SET nickname = ?, age = ?, gender = ?, interests = ?, bio = ?
                     WHERE id = ?''',
                  (nickname, int(age) if age else None, gender,
                   interests_str, bio, session['user_id']))
        conn.commit()
        conn.close()

        # 昵称变了，同步更新session（顶部导航和页面里显示用）
        session['nickname'] = nickname
        return redirect(url_for('profile'))

    # GET：把已保存的资料查出来，回填到表单（空值显示为空）
    c.execute('SELECT nickname, age, gender, interests, bio FROM users WHERE id = ?',
              (session['user_id'],))
    user = c.fetchone()
    conn.close()

    return render_template('edit_profile.html', error='',
                           nickname=user[0] or '', age=user[1] or '',
                           gender=user[2] or '', interests=user[3] or '',
                           bio=user[4] or '', suggest_tags=SUGGEST_TAGS)

# 删除帖子（软删除）
@app.route('/post/<int:post_id>/delete', methods=['POST'])
def delete_post(post_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('UPDATE posts SET status = 0 WHERE id = ? AND user_id = ?',
              (post_id, session['user_id']))
    conn.commit()
    conn.close()

    return redirect(url_for('profile'))

# ==================== 启动 ====================
if __name__ == '__main__':
    init_db()
    print("🚀 校园搭子APP启动成功！")
    print("📱 请在浏览器打开: http://127.0.0.1:5000")
    app.run(debug=True, host='0.0.0.0', port=5000)
