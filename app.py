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
        g.db.execute("PRAGMA foreign_keys = ON")
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
            status TEXT DEFAULT '待审核',
            reviewer TEXT,
            review_date TEXT,
            comments TEXT,
            score INTEGER,
            FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
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
            FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS business_cases (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id INTEGER NOT NULL,
            investment REAL,
            expected_revenue REAL,
            roi REAL,
            payback_months INTEGER,
            risk_level TEXT,
            conclusion TEXT,
            created_at TEXT DEFAULT (datetime('now','localtime')),
            FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS activities (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id INTEGER,
            user_id INTEGER,
            action TEXT NOT NULL,
            detail TEXT,
            created_at TEXT DEFAULT (datetime('now','localtime')),
            FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
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
        ('admin','admin123','管理员','管理员','管理部'),
        ('zhangsan','123456','张三','产品经理','产品部'),
        ('lisi','123456','李四','市场经理','市场部'),
    ])
    # Projects
    db.executemany("INSERT INTO projects(name,description,category,current_stage,status,owner_id,target_launch_date,progress) VALUES(?,?,?,?,?,?,?,?)", [
        ('有机婴幼儿奶粉3段升级','针对12-36月龄婴幼儿的有机配方奶粉升级，强化DHA、ARA及益生元组合，提升免疫力与消化吸收。','奶粉','商业论证','进行中',2,'2026-09-01',65),
        ('智能恒温婴儿睡袋','集成温控芯片与透气面料，自动调节睡袋内温度，配套APP实时监测宝宝睡眠状态。','智能穿戴','概念验证','进行中',2,'2026-12-15',40),
        ('天然植物婴儿湿巾','采用99.9%天然植物成分，零添加防腐剂与酒精，通过SGS与欧盟REACH认证。','洗护用品','上市准备','进行中',3,'2026-06-01',82),
        ('益生菌儿童软糖系列','针对3-12岁儿童的益生菌软糖，含鼠李糖乳杆菌与动物双歧杆菌，改善肠道健康。','营养食品','市场洞察','进行中',3,'2027-03-01',20),
    ])
    # Stage gates for each project
    project_stages = [
        # Project 1: 奶粉 - at 商业论证 (stages 1-2 passed, 3 in review)
        (1, [('已通过',88,'李四'),('已通过',85,'张三'),('审核中',None,'管理员'),('待启动',None,None),('待启动',None,None),('待启动',None,None)]),
        # Project 2: 睡袋 - at 概念验证 (stage 1 passed, 2 in review)
        (2, [('已通过',82,'李四'),('审核中',None,'张三'),('待启动',None,None),('待启动',None,None),('待启动',None,None),('待启动',None,None)]),
        # Project 3: 湿巾 - at 上市准备 (stages 1-3 passed, 4 in review)
        (3, [('已通过',90,'李四'),('已通过',92,'张三'),('已通过',87,'管理员'),('审核中',None,'张三'),('待启动',None,None),('待启动',None,None)]),
        # Project 4: 软糖 - at 市场洞察 (stage 1 in review)
        (4, [('审核中',None,'李四'),('待启动',None,None),('待启动',None,None),('待启动',None,None),('待启动',None,None),('待启动',None,None)]),
    ]
    for pid, stages in project_stages:
        for i, (status, score, reviewer) in enumerate(stages):
            review_date = '2026-03-01' if status == '已通过' else None
            db.execute("INSERT INTO stage_gates(project_id,stage_name,stage_order,status,reviewer,review_date,score) VALUES(?,?,?,?,?,?,?)",
                       (pid, STAGES[i], i+1, status, reviewer, review_date, score))
    # Market insights
    db.executemany("INSERT INTO market_insights(project_id,title,insight_type,content,source,created_by) VALUES(?,?,?,?,?,?)", [
        (1,'有机奶粉市场规模持续扩大','市场趋势','2025年中国有机婴幼儿奶粉市场规模达180亿元，同比增长22%。消费者对有机认证的关注度提升35%。','尼尔森IQ 2025母婴报告',3),
        (1,'3段奶粉消费者偏好调研','消费者洞察','调研显示78%的妈妈关注DHA含量，65%重视益生元配方，52%愿意为有机认证支付溢价20-30%。','内部消费者调研（N=2000）',3),
        (2,'智能母婴穿戴市场机会','市场趋势','全球智能婴儿监测设备市场预计2026年达45亿美元，中国市场占比18%，年增速超30%。','Grand View Research',3),
        (2,'婴儿睡眠痛点分析','消费者洞察','82%的新手父母反馈夜间频繁查看宝宝冷暖是最大困扰。恒温睡袋概念测试好感度达87%。','焦点小组访谈（6组）',2),
        (3,'婴儿湿巾品类消费升级','竞品分析','头部品牌纷纷推出"成分党"湿巾，主打零添加。市场均价从0.15元/片提升至0.28元/片。','魔镜市场情报',3),
        (3,'电商渠道湿巾销售趋势','渠道洞察','抖音电商母婴湿巾GMV同比增长156%，内容种草转化率显著高于传统电商。','蝉妈妈数据',3),
        (4,'儿童益生菌软糖消费趋势','市场趋势','儿童功能性零食市场年增长率28%，益生菌软糖品类渗透率仅12%，存在巨大增长空间。','艾瑞咨询',3),
        (4,'竞品益生菌产品分析','竞品分析','目前市场主流产品以胶囊和粉剂为主，软糖剂型仅占8%。软糖形式儿童接受度高达93%。','内部竞品调研',3),
    ])
    # Business cases
    db.executemany("INSERT INTO business_cases(project_id,investment,expected_revenue,roi,payback_months,risk_level,conclusion) VALUES(?,?,?,?,?,?,?)", [
        (1,2500,8500,240,14,'中','有机奶粉3段升级项目投资回报率达240%，建议推进。需关注有机原料供应链稳定性与认证周期。'),
        (3,800,3200,300,8,'低','天然植物湿巾项目风险可控，投资回收期短，渠道已就绪，建议加速上市。'),
    ])
    # Activities
    now = datetime.now()
    acts = [
        (1,2,'更新项目','更新了商业论证阶段的财务预测模型', now - timedelta(hours=2)),
        (1,3,'添加洞察','新增市场洞察：有机奶粉市场规模持续扩大', now - timedelta(hours=5)),
        (2,2,'创建项目','创建了新项目：智能恒温婴儿睡袋', now - timedelta(days=1)),
        (3,3,'阶段审核','商业论证阶段审核通过，评分95分', now - timedelta(days=2)),
        (3,2,'更新项目','更新上市准备阶段：渠道铺货进度80%', now - timedelta(days=3)),
        (4,3,'添加洞察','新增竞品分析：竞品益生菌产品分析', now - timedelta(days=4)),
        (1,1,'阶段审核','概念验证阶段审核通过，评分85分', now - timedelta(days=5)),
        (2,3,'添加洞察','新增市场趋势：智能母婴穿戴市场机会', now - timedelta(days=6)),
    ]
    for pid, uid, action, detail, ts in acts:
        db.execute("INSERT INTO activities(project_id,user_id,action,detail,created_at) VALUES(?,?,?,?,?)",
                   (pid, uid, action, detail, ts.strftime('%Y-%m-%d %H:%M:%S')))
    # Knowledge base
    db.executemany("INSERT INTO knowledge_base(title,category,content,author,usage_count) VALUES(?,?,?,?,?)", [
        ('母婴新品Stage-Gate流程指南','流程规范','本指南定义了母婴新品从市场洞察到复盘优化的6个阶段门禁流程，每个阶段的交付物要求、评审标准和决策规则。','管理员',45),
        ('消费者调研方法论','调研方法','涵盖定性（焦点小组、深度访谈）与定量（问卷调研、A/B测试）方法，附母婴品类专用调研模板与样本量计算器。','李四',38),
        ('婴幼儿食品法规汇编','法规合规','汇总GB10765-2021、GB10767-2021等婴幼儿食品国标要求，以及有机产品认证流程与时间线。','张三',62),
        ('商业论证模型模板','商业分析','标准化的NPD商业论证Excel模板，包含投资估算、收入预测、ROI计算、敏感性分析与风险评估矩阵。','管理员',55),
        ('母婴品类电商运营手册','市场营销','覆盖天猫、京东、抖音、小红书四大平台的母婴品类运营策略，含内容种草、达人合作与促销节奏规划。','李四',33),
        ('供应链质量管理SOP','质量管理','母婴产品供应链全流程质量管控标准操作流程，涵盖原料验收、生产监控、成品检验与追溯体系。','张三',41),
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
    active = query_db("SELECT COUNT(*) as c FROM projects WHERE status='进行中'", one=True)['c']
    total_insights = query_db("SELECT COUNT(*) as c FROM market_insights", one=True)['c']
    pending_reviews = query_db("SELECT COUNT(*) as c FROM stage_gates WHERE status='审核中'", one=True)['c']
    avg_row = query_db("SELECT AVG(progress) as avg_p FROM projects WHERE status='进行中'", one=True)
    avg_progress = round(avg_row['avg_p'] or 0, 1)
    stage_counts = query_db("SELECT current_stage as stage, COUNT(*) as count FROM projects GROUP BY current_stage")
    recent = query_db("""
        SELECT a.*, u.real_name as user_name, p.name as project_name
        FROM activities a LEFT JOIN users u ON a.user_id=u.id LEFT JOIN projects p ON a.project_id=p.id
        ORDER BY a.created_at DESC LIMIT 10
    """)
    return jsonify({
        'total_projects': total,
        'active_projects': active,
        'total_insights': total_insights,
        'pending_reviews': pending_reviews,
        'avg_progress': avg_progress,
        'stage_counts': stage_counts,
        'recent_activities': recent,
    })

@app.route('/api/pipeline')
@login_required
def api_pipeline():
    result = []
    for stage in STAGES:
        count = query_db("SELECT COUNT(*) as c FROM projects WHERE current_stage=?", (stage,), one=True)['c']
        projects_in_stage = query_db("SELECT id, name, progress, status FROM projects WHERE current_stage=?", (stage,))
        result.append({
            'stage': stage,
            'count': count,
            'projects': projects_in_stage,
        })
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
        status = '审核中' if i == 0 else '待启动'
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
               (data.get('status','审核中'), data.get('reviewer'), data.get('review_date'), data.get('comments'), data.get('score'), pid, stage_name))
    # If completing a stage, activate next
    if data.get('status') == '已通过':
        current_order = query_db("SELECT stage_order FROM stage_gates WHERE project_id=? AND stage_name=?", (pid, stage_name), one=True)
        if current_order:
            next_order = current_order['stage_order'] + 1
            next_stage = query_db("SELECT stage_name FROM stage_gates WHERE project_id=? AND stage_order=?", (pid, next_order), one=True)
            if next_stage:
                execute_db("UPDATE stage_gates SET status='审核中' WHERE project_id=? AND stage_order=?", (pid, next_order))
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
