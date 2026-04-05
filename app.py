import os
import sqlite3
import json
from datetime import datetime, timedelta
from functools import wraps
from flask import Flask, request, jsonify, session, render_template, redirect, url_for, g

app = Flask(__name__)
app.secret_key = 'ipms-secret-key-2025'
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'ipms.db')

STAGES = ['市场洞察', '概念验证', '商业论证', '上市准备', '发布执行', '复盘优化']

# ─── Database helpers ───

def get_db():
    if 'db' not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA journal_mode=WAL")
    return g.db

@app.teardown_appcontext
def close_db(exception):
    db = g.pop('db', None)
    if db is not None:
        db.close()

def query_db(query, args=(), one=False):
    cur = get_db().execute(query, args)
    rv = [dict(row) for row in cur.fetchall()]
    return (rv[0] if rv else None) if one else rv

def execute_db(query, args=()):
    db = get_db()
    cur = db.execute(query, args)
    db.commit()
    return cur.lastrowid

# ─── Auth decorator ───

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            if request.is_json or request.path.startswith('/api/'):
                return jsonify({'error': '未登录'}), 401
            return redirect(url_for('login_page'))
        return f(*args, **kwargs)
    return decorated

# ─── Database init & seed ───

def init_db():
    db = sqlite3.connect(DB_PATH)
    db.executescript('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            real_name TEXT NOT NULL,
            role TEXT NOT NULL,
            department TEXT,
            created_at TEXT DEFAULT (datetime('now','localtime'))
        );
        CREATE TABLE IF NOT EXISTS projects (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            description TEXT,
            category TEXT,
            current_stage TEXT NOT NULL,
            status TEXT DEFAULT '进行中',
            owner_id INTEGER,
            created_at TEXT DEFAULT (datetime('now','localtime')),
            updated_at TEXT DEFAULT (datetime('now','localtime')),
            target_launch_date TEXT,
            progress INTEGER DEFAULT 0,
            FOREIGN KEY (owner_id) REFERENCES users(id)
        );
        CREATE TABLE IF NOT EXISTS stage_gates (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id INTEGER NOT NULL,
            stage_name TEXT NOT NULL,
            stage_order INTEGER NOT NULL,
            status TEXT DEFAULT 'pending',
            reviewer TEXT,
            review_date TEXT,
            comments TEXT,
            score INTEGER,
            FOREIGN KEY (project_id) REFERENCES projects(id)
        );
        CREATE TABLE IF NOT EXISTS market_insights (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id INTEGER NOT NULL,
            title TEXT NOT NULL,
            insight_type TEXT,
            content TEXT,
            source TEXT,
            created_at TEXT DEFAULT (datetime('now','localtime')),
            created_by INTEGER,
            FOREIGN KEY (project_id) REFERENCES projects(id)
        );
        CREATE TABLE IF NOT EXISTS business_cases (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id INTEGER UNIQUE NOT NULL,
            investment REAL,
            expected_revenue REAL,
            roi REAL,
            payback_months INTEGER,
            risk_level TEXT,
            conclusion TEXT,
            created_at TEXT DEFAULT (datetime('now','localtime')),
            FOREIGN KEY (project_id) REFERENCES projects(id)
        );
        CREATE TABLE IF NOT EXISTS activities (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id INTEGER,
            user_id INTEGER,
            action TEXT NOT NULL,
            detail TEXT,
            created_at TEXT DEFAULT (datetime('now','localtime')),
            FOREIGN KEY (project_id) REFERENCES projects(id)
        );
        CREATE TABLE IF NOT EXISTS knowledge_base (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            category TEXT,
            content TEXT,
            author TEXT,
            usage_count INTEGER DEFAULT 0,
            created_at TEXT DEFAULT (datetime('now','localtime'))
        );
    ''')
    # Seed if empty
    count = db.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    if count == 0:
        seed_data(db)
    db.close()

def seed_data(db):
    # Users
    db.executemany("INSERT INTO users(username,password,real_name,role,department) VALUES(?,?,?,?,?)", [
        ('admin','admin123','系统管理员','管理员','数字化部门'),
        ('zhangsan','123456','张三','产品经理','产品部'),
        ('lisi','123456','李四','市场经理','市场部'),
    ])
    # Projects
    db.executemany("INSERT INTO projects(name,description,category,current_stage,status,owner_id,target_launch_date,progress) VALUES(?,?,?,?,?,?,?,?)", [
        ('有机婴幼儿奶粉3段升级','针对12-36个月宝宝的有机奶粉升级配方，添加乳铁蛋白和DHA','奶粉','商业论证','进行中',2,'2025-06-30',65),
        ('智能恒温婴儿睡袋','采用相变材料技术，自动调节睡袋内部温度，保持婴儿舒适睡眠','用品','概念验证','进行中',2,'2025-09-15',40),
        ('天然植物婴儿湿巾','100%植物纤维，添加金盏花和洋甘菊精华，零添加防腐剂','日用品','上市准备','进行中',3,'2025-04-20',82),
        ('益生菌儿童软糖系列','针对3-12岁儿童的益生菌软糖，改善肠道健康，多种水果口味','食品','市场洞察','进行中',3,'2025-12-01',20),
    ])
    # Stage gates for each project
    project_stages = [
        # Project 1: 奶粉 - at 商业论证
        (1, [('completed',95,'张三'),('completed',88,'张三'),('active',None,None),('pending',None,None),('pending',None,None),('pending',None,None)]),
        # Project 2: 睡袋 - at 概念验证
        (2, [('completed',90,'李四'),('active',None,None),('pending',None,None),('pending',None,None),('pending',None,None),('pending',None,None)]),
        # Project 3: 湿巾 - at 上市准备
        (3, [('completed',92,'李四'),('completed',85,'张三'),('completed',91,'张三'),('active',None,None),('pending',None,None),('pending',None,None)]),
        # Project 4: 软糖 - at 市场洞察
        (4, [('active',None,None),('pending',None,None),('pending',None,None),('pending',None,None),('pending',None,None),('pending',None,None)]),
    ]
    for pid, stages in project_stages:
        for i, (status, score, reviewer) in enumerate(stages):
            review_date = '2025-03-15' if status == 'completed' else None
            db.execute("INSERT INTO stage_gates(project_id,stage_name,stage_order,status,reviewer,review_date,score) VALUES(?,?,?,?,?,?,?)",
                       (pid, STAGES[i], i+1, status, reviewer, review_date, score))
    # Market insights
    db.executemany("INSERT INTO market_insights(project_id,title,insight_type,content,source,created_by) VALUES(?,?,?,?,?,?)", [
        (1,'有机奶粉市场年增长25%','趋势分析','2024年中国有机婴幼儿奶粉市场规模达120亿元，同比增长25%，预计2025年将突破150亿元','艾瑞咨询2024母婴行业报告',3),
        (1,'消费者更关注配方透明度','消费者研究','调研显示78%的妈妈在购买奶粉时最关注配方成分表，其次是品牌口碑(65%)和价格(52%)','内部消费者调研N=2000',3),
        (2,'婴儿睡眠产品市场缺口','需求洞察','目前市场上缺乏真正智能化的婴儿睡眠产品，家长对恒温睡袋的需求未被满足','母婴社区用户分析',3),
        (4,'益生菌品类年增长35%','趋势分析','儿童益生菌市场快速增长，软糖剂型接受度最高，家长偏好天然水果口味','天猫健康品类报告',3),
        (4,'竞品分析：现有产品口感差','竞品分析','主要竞品益生菌产品以胶囊和粉剂为主，儿童接受度低，软糖形态有明显差异化优势','竞品调研报告',3),
        (3,'天然成分湿巾需求增长','趋势分析','无添加、植物基婴儿湿巾需求增长40%，消费者愿意为天然成分支付20-30%溢价','京东母婴品类数据',3),
    ])
    # Business cases
    db.executemany("INSERT INTO business_cases(project_id,investment,expected_revenue,roi,payback_months,risk_level,conclusion) VALUES(?,?,?,?,?,?,?)", [
        (1,350,1200,185,14,'中','投资回报率185%，14个月回本。有机奶粉市场持续增长，配方升级后竞争力显著提升，建议立即推进。'),
        (3,180,650,210,10,'低','天然植物湿巾市场需求旺盛，投资回报率210%，10个月回本，风险较低。渠道铺货已启动。'),
    ])
    # Activities
    now = datetime.now()
    acts = [
        (1,2,'通过评审','有机奶粉3段通过商业可行性评审，ROI预估达到185%', now - timedelta(hours=2)),
        (2,3,'上传报告','智能睡袋消费者测试报告已上传，好评率92%', now - timedelta(hours=5)),
        (3,3,'渠道进展','婴儿湿巾华东区渠道铺货完成78%，预计本周达标', now - timedelta(hours=20)),
        (4,3,'完成洞察','儿童软糖市场洞察报告完成，发现益生菌品类年增长35%', now - timedelta(hours=30)),
        (1,2,'PLM同步','PLM系统同步：有机奶粉3段配方定版完成，转入商业论证', now - timedelta(hours=48)),
        (None,2,'知识库更新','知识库新增：《母婴品类2025渠道策略白皮书》已发布', now - timedelta(hours=72)),
    ]
    for pid, uid, action, detail, ts in acts:
        db.execute("INSERT INTO activities(project_id,user_id,action,detail,created_at) VALUES(?,?,?,?,?)",
                   (pid, uid, action, detail, ts.strftime('%Y-%m-%d %H:%M:%S')))
    # Knowledge base
    db.executemany("INSERT INTO knowledge_base(title,category,content,author,usage_count) VALUES(?,?,?,?,?)", [
        ('新品立项评估模板','方法论模板','包含市场分析、竞品对标、财务预测、风险评估四大板块的标准化立项评估模板','张三',236),
        ('ROI测算工具','方法论模板','基于历史数据和市场预测的ROI自动测算模型，支持多场景模拟','张三',189),
        ('上市复盘检查清单','方法论模板','涵盖产品、渠道、营销、供应链四个维度的上市复盘标准检查清单','李四',145),
        ('GTM策略画布','方法论模板','Go-To-Market策略规划画布，包含目标用户、价值主张、渠道策略、定价策略','张三',167),
        ('2024有机奶粉上市案例','历史案例','有机奶粉2段升级项目全流程复盘，成功经验和踩坑总结','张三',98),
        ('婴儿湿巾市场进入策略','历史案例','天然婴儿湿巾品类从0到1的市场进入策略，含渠道选择和定价方案','李四',76),
        ('母婴品类2025渠道策略白皮书','行业报告','覆盖线上电商、线下母婴店、医院渠道的全渠道策略分析','市场部',112),
        ('消费者需求洞察方法论','最佳实践','母婴行业消费者需求挖掘的系统化方法论，含调研设计和分析框架','张三',88),
    ])
    db.commit()

# ─── API: Auth ───

@app.route('/api/login', methods=['POST'])
def api_login():
    data = request.get_json()
    user = query_db("SELECT * FROM users WHERE username=? AND password=?",
                     (data.get('username',''), data.get('password','')), one=True)
    if user:
        session['user_id'] = user['id']
        session['username'] = user['username']
        session['real_name'] = user['real_name']
        session['role'] = user['role']
        return jsonify({'success': True, 'user': {'id': user['id'], 'real_name': user['real_name'], 'role': user['role']}})
    return jsonify({'success': False, 'error': '用户名或密码错误'}), 401

@app.route('/api/logout', methods=['POST'])
def api_logout():
    session.clear()
    return jsonify({'success': True})

@app.route('/api/user')
@login_required
def api_user():
    user = query_db("SELECT id,username,real_name,role,department FROM users WHERE id=?", (session['user_id'],), one=True)
    return jsonify(user)

# ─── API: Dashboard ───

@app.route('/api/dashboard/stats')
@login_required
def api_dashboard_stats():
    total = query_db("SELECT COUNT(*) as c FROM projects", one=True)['c']
    reviewing = query_db("SELECT COUNT(DISTINCT project_id) as c FROM stage_gates WHERE status='active'", one=True)['c']
    knowledge = query_db("SELECT COUNT(*) as c FROM knowledge_base", one=True)['c']
    return jsonify({
        'total_projects': total,
        'success_rate': 78,
        'reviewing': reviewing,
        'knowledge_count': knowledge,
    })

@app.route('/api/pipeline')
@login_required
def api_pipeline():
    result = {}
    for stage in STAGES:
        count = query_db("SELECT COUNT(*) as c FROM projects WHERE current_stage=?", (stage,), one=True)['c']
        result[stage] = count
    return jsonify(result)

# ─── API: Projects ───

@app.route('/api/projects', methods=['GET'])
@login_required
def api_projects():
    projects = query_db("""
        SELECT p.*, u.real_name as owner_name
        FROM projects p LEFT JOIN users u ON p.owner_id=u.id
        ORDER BY p.updated_at DESC
    """)
    return jsonify(projects)

@app.route('/api/projects', methods=['POST'])
@login_required
def api_create_project():
    data = request.get_json()
    pid = execute_db(
        "INSERT INTO projects(name,description,category,current_stage,owner_id,target_launch_date,progress) VALUES(?,?,?,?,?,?,?)",
        (data['name'], data.get('description',''), data.get('category',''), '市场洞察', session['user_id'], data.get('target_launch_date',''), 0)
    )
    # Create stage gates
    for i, stage in enumerate(STAGES):
        status = 'active' if i == 0 else 'pending'
        execute_db("INSERT INTO stage_gates(project_id,stage_name,stage_order,status) VALUES(?,?,?,?)", (pid, stage, i+1, status))
    execute_db("INSERT INTO activities(project_id,user_id,action,detail) VALUES(?,?,?,?)",
               (pid, session['user_id'], '创建项目', f'创建新项目：{data["name"]}'))
    return jsonify({'success': True, 'id': pid}), 201

@app.route('/api/projects/<int:pid>', methods=['GET'])
@login_required
def api_project_detail(pid):
    project = query_db("SELECT p.*, u.real_name as owner_name FROM projects p LEFT JOIN users u ON p.owner_id=u.id WHERE p.id=?", (pid,), one=True)
    if not project:
        return jsonify({'error': '项目不存在'}), 404
    project['stages'] = query_db("SELECT * FROM stage_gates WHERE project_id=? ORDER BY stage_order", (pid,))
    return jsonify(project)

@app.route('/api/projects/<int:pid>', methods=['PUT'])
@login_required
def api_update_project(pid):
    data = request.get_json()
    fields = []
    values = []
    for key in ['name','description','category','current_stage','status','progress','target_launch_date']:
        if key in data:
            fields.append(f"{key}=?")
            values.append(data[key])
    if fields:
        fields.append("updated_at=datetime('now','localtime')")
        values.append(pid)
        execute_db(f"UPDATE projects SET {','.join(fields)} WHERE id=?", values)
    return jsonify({'success': True})

@app.route('/api/projects/<int:pid>', methods=['DELETE'])
@login_required
def api_delete_project(pid):
    execute_db("DELETE FROM stage_gates WHERE project_id=?", (pid,))
    execute_db("DELETE FROM market_insights WHERE project_id=?", (pid,))
    execute_db("DELETE FROM business_cases WHERE project_id=?", (pid,))
    execute_db("DELETE FROM activities WHERE project_id=?", (pid,))
    execute_db("DELETE FROM projects WHERE id=?", (pid,))
    return jsonify({'success': True})

# ─── API: Stage Gates ───

@app.route('/api/projects/<int:pid>/stages', methods=['GET'])
@login_required
def api_stages(pid):
    stages = query_db("SELECT * FROM stage_gates WHERE project_id=? ORDER BY stage_order", (pid,))
    return jsonify(stages)

@app.route('/api/projects/<int:pid>/stages', methods=['POST'])
@login_required
def api_update_stage(pid):
    data = request.get_json()
    stage_name = data['stage_name']
    execute_db("UPDATE stage_gates SET status=?, reviewer=?, review_date=?, comments=?, score=? WHERE project_id=? AND stage_name=?",
               (data.get('status','active'), data.get('reviewer'), data.get('review_date'), data.get('comments'), data.get('score'), pid, stage_name))
    # If completing a stage, activate next
    if data.get('status') == 'completed':
        current_order = query_db("SELECT stage_order FROM stage_gates WHERE project_id=? AND stage_name=?", (pid, stage_name), one=True)
        if current_order:
            next_order = current_order['stage_order'] + 1
            next_stage = query_db("SELECT stage_name FROM stage_gates WHERE project_id=? AND stage_order=?", (pid, next_order), one=True)
            if next_stage:
                execute_db("UPDATE stage_gates SET status='active' WHERE project_id=? AND stage_order=?", (pid, next_order))
                execute_db("UPDATE projects SET current_stage=?, updated_at=datetime('now','localtime') WHERE id=?", (next_stage['stage_name'], pid))
        execute_db("INSERT INTO activities(project_id,user_id,action,detail) VALUES(?,?,?,?)",
                   (pid, session['user_id'], '通过评审', f'{stage_name}阶段评审通过'))
    return jsonify({'success': True})

# ─── API: Market Insights ───

@app.route('/api/projects/<int:pid>/insights', methods=['GET'])
@login_required
def api_insights(pid):
    insights = query_db("SELECT * FROM market_insights WHERE project_id=? ORDER BY created_at DESC", (pid,))
    return jsonify(insights)

@app.route('/api/projects/<int:pid>/insights', methods=['POST'])
@login_required
def api_add_insight(pid):
    data = request.get_json()
    execute_db("INSERT INTO market_insights(project_id,title,insight_type,content,source,created_by) VALUES(?,?,?,?,?,?)",
               (pid, data['title'], data.get('insight_type',''), data.get('content',''), data.get('source',''), session['user_id']))
    return jsonify({'success': True}), 201

@app.route('/api/insights', methods=['GET'])
@login_required
def api_all_insights():
    insights = query_db("""
        SELECT mi.*, p.name as project_name
        FROM market_insights mi LEFT JOIN projects p ON mi.project_id=p.id
        ORDER BY mi.created_at DESC
    """)
    return jsonify(insights)

# ─── API: Business Cases ───

@app.route('/api/projects/<int:pid>/business-case', methods=['GET'])
@login_required
def api_business_case(pid):
    bc = query_db("SELECT * FROM business_cases WHERE project_id=?", (pid,), one=True)
    return jsonify(bc or {})

@app.route('/api/projects/<int:pid>/business-case', methods=['POST'])
@login_required
def api_save_business_case(pid):
    data = request.get_json()
    existing = query_db("SELECT id FROM business_cases WHERE project_id=?", (pid,), one=True)
    if existing:
        execute_db("UPDATE business_cases SET investment=?,expected_revenue=?,roi=?,payback_months=?,risk_level=?,conclusion=? WHERE project_id=?",
                   (data.get('investment',0), data.get('expected_revenue',0), data.get('roi',0), data.get('payback_months',0), data.get('risk_level','中'), data.get('conclusion',''), pid))
    else:
        execute_db("INSERT INTO business_cases(project_id,investment,expected_revenue,roi,payback_months,risk_level,conclusion) VALUES(?,?,?,?,?,?,?)",
                   (pid, data.get('investment',0), data.get('expected_revenue',0), data.get('roi',0), data.get('payback_months',0), data.get('risk_level','中'), data.get('conclusion','')))
    return jsonify({'success': True})

# ─── API: Activities ───

@app.route('/api/activities', methods=['GET'])
@login_required
def api_activities():
    pid = request.args.get('project_id')
    if pid:
        activities = query_db("""
            SELECT a.*, u.real_name as user_name, p.name as project_name
            FROM activities a LEFT JOIN users u ON a.user_id=u.id LEFT JOIN projects p ON a.project_id=p.id
            WHERE a.project_id=? ORDER BY a.created_at DESC LIMIT 20
        """, (pid,))
    else:
        activities = query_db("""
            SELECT a.*, u.real_name as user_name, p.name as project_name
            FROM activities a LEFT JOIN users u ON a.user_id=u.id LEFT JOIN projects p ON a.project_id=p.id
            ORDER BY a.created_at DESC LIMIT 20
        """)
    return jsonify(activities)

@app.route('/api/activities', methods=['POST'])
@login_required
def api_add_activity():
    data = request.get_json()
    execute_db("INSERT INTO activities(project_id,user_id,action,detail) VALUES(?,?,?,?)",
               (data.get('project_id'), session['user_id'], data['action'], data.get('detail','')))
    return jsonify({'success': True}), 201

# ─── API: Knowledge Base ───

@app.route('/api/knowledge', methods=['GET'])
@login_required
def api_knowledge():
    category = request.args.get('category')
    if category:
        items = query_db("SELECT * FROM knowledge_base WHERE category=? ORDER BY usage_count DESC", (category,))
    else:
        items = query_db("SELECT * FROM knowledge_base ORDER BY usage_count DESC")
    return jsonify(items)

@app.route('/api/knowledge', methods=['POST'])
@login_required
def api_add_knowledge():
    data = request.get_json()
    execute_db("INSERT INTO knowledge_base(title,category,content,author) VALUES(?,?,?,?)",
               (data['title'], data.get('category',''), data.get('content',''), session.get('real_name','')))
    return jsonify({'success': True}), 201

# ─── Page Routes ───

@app.route('/')
def index():
    return redirect(url_for('login_page'))

@app.route('/login')
def login_page():
    return render_template('login.html')

@app.route('/dashboard')
@login_required
def dashboard_page():
    return render_template('dashboard.html')

@app.route('/project/<int:pid>')
@login_required
def project_page(pid):
    return render_template('project_detail.html', project_id=pid)

@app.route('/pipeline')
@login_required
def pipeline_page():
    return render_template('pipeline.html')

@app.route('/insights')
@login_required
def insights_page():
    return render_template('insights.html')

@app.route('/business-case/<int:pid>')
@login_required
def business_case_page(pid):
    return render_template('business_case.html', project_id=pid)

@app.route('/knowledge')
@login_required
def knowledge_page():
    return render_template('knowledge.html')

if __name__ == '__main__':
    init_db()
    app.run(host='0.0.0.0', port=5001, debug=True)
