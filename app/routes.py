import os
import re
import requests as http_req
from flask import Blueprint, render_template, redirect, url_for, request, flash
from flask_login import login_user, logout_user, login_required, current_user
from app import db
from app.models import User, Transaction
from datetime import datetime

main = Blueprint('main', __name__)

# ══════════════════════════════════════════
# META WHATSAPP CLOUD API
# ══════════════════════════════════════════

WHATSAPP_API = "https://graph.facebook.com/v22.0"

def get_cfg():
    return {
        'token':    os.environ.get('WHATSAPP_TOKEN', ''),
        'phone_id': os.environ.get('WHATSAPP_PHONE_ID', ''),
        'verify':   os.environ.get('META_VERIFY_TOKEN', 'ledgr_verify_2026'),
    }

def send_whatsapp(to, message):
    cfg = get_cfg()
    if not cfg['token'] or not cfg['phone_id']:
        print(f"[WA] Config missing — to:{to} msg:{message[:60]}")
        return False
    url = f"{WHATSAPP_API}/{cfg['phone_id']}/messages"
    headers = {
        "Authorization": f"Bearer {cfg['token']}",
        "Content-Type": "application/json"
    }
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "text",
        "text": {"body": message, "preview_url": False}
    }
    try:
        r = http_req.post(url, headers=headers, json=payload, timeout=10)
        print(f"[WA] {r.status_code} → {to}")
        if r.status_code != 200:
            print(f"[WA] Error body: {r.text}")
        return r.status_code == 200
    except Exception as e:
        print(f"[WA] Exception: {e}")
        return False

def mark_read(message_id):
    cfg = get_cfg()
    if not cfg['token'] or not cfg['phone_id']:
        return
    try:
        http_req.post(
            f"{WHATSAPP_API}/{cfg['phone_id']}/messages",
            headers={"Authorization": f"Bearer {cfg['token']}", "Content-Type": "application/json"},
            json={"messaging_product": "whatsapp", "status": "read", "message_id": message_id},
            timeout=5
        )
    except:
        pass

# ══════════════════════════════════════════
# GREETING
# ══════════════════════════════════════════

def get_greeting():
    h = datetime.now().hour
    if 5 <= h < 12:    return "Good Morning"
    elif 12 <= h < 17: return "Good Afternoon"
    elif 17 <= h < 21: return "Good Evening"
    else:              return "Night Owl"

def get_greeting_sub():
    h = datetime.now().hour
    if 5 <= h < 12:    return "Here's your financial overview to start the day."
    elif 12 <= h < 17: return "Your finances are looking sharp. Here's where things stand."
    elif 17 <= h < 21: return "Winding down? Here's a summary of your day's activity."
    else:              return "Burning the midnight oil? Your finances are right here."

def get_totals(user_id):
    inc = db.session.query(db.func.sum(Transaction.amount)).filter_by(user_id=user_id, type='income').scalar() or 0
    exp = db.session.query(db.func.sum(Transaction.amount)).filter_by(user_id=user_id, type='expense').scalar() or 0
    return float(inc), float(exp), float(inc - exp)

# ══════════════════════════════════════════
# WEB ROUTES
# ══════════════════════════════════════════

@main.route('/')
def index():
    return redirect(url_for('main.dashboard') if current_user.is_authenticated else url_for('main.login'))

@main.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        name  = request.form.get('name', '').strip()
        email = request.form.get('email', '').strip().lower()
        pw    = request.form.get('password', '')
        if not name or not email or not pw:
            flash('All fields are required.')
            return redirect(url_for('main.register'))
        if User.query.filter_by(email=email).first():
            flash('An account with this email already exists.')
            return redirect(url_for('main.register'))
        u = User(name=name, email=email)
        u.set_password(pw)
        db.session.add(u)
        db.session.commit()
        flash('Account created. Welcome to Ledgr.')
        return redirect(url_for('main.login'))
    return render_template('register.html')

@main.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        u = User.query.filter_by(email=request.form.get('email','').strip().lower()).first()
        if u and u.check_password(request.form.get('password', '')):
            login_user(u)
            return redirect(url_for('main.dashboard'))
        flash('Invalid email or password. Please try again.')
    return render_template('login.html')

@main.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('main.login'))

@main.route('/dashboard')
@login_required
def dashboard():
    txns = Transaction.query.filter_by(
        user_id=current_user.id
    ).order_by(Transaction.date.desc()).limit(10).all()
    inc, exp, bal = get_totals(current_user.id)
    return render_template('dashboard.html',
        transactions=txns,
        total_income=inc, total_expense=exp, balance=bal,
        greeting=get_greeting(), greeting_sub=get_greeting_sub()
    )

@main.route('/add', methods=['GET', 'POST'])
@login_required
def add_transaction():
    inc, exp, bal = get_totals(current_user.id)
    if request.method == 'POST':
        amt_raw = request.form.get('amount', '0')
        try:
            amt = float(amt_raw)
        except:
            flash('Invalid amount.')
            return redirect(url_for('main.add_transaction'))
        txn = Transaction(
            user_id=current_user.id,
            type=request.form.get('type'),
            amount=amt,
            category=request.form.get('category'),
            description=request.form.get('description', '').strip(),
            date=datetime.now()
        )
        db.session.add(txn)
        db.session.commit()
        flash('Transaction recorded successfully.')
        return redirect(url_for('main.dashboard'))
    return render_template('add_transaction.html', total_income=inc, total_expense=exp, balance=bal)

@main.route('/edit/<int:id>', methods=['GET', 'POST'])
@login_required
def edit_transaction(id):
    txn = Transaction.query.get_or_404(id)
    if txn.user_id != current_user.id:
        return redirect(url_for('main.dashboard'))
    inc, exp, bal = get_totals(current_user.id)
    if request.method == 'POST':
        try:
            txn.amount = float(request.form.get('amount', 0))
        except:
            flash('Invalid amount.')
            return redirect(url_for('main.edit_transaction', id=id))
        txn.type        = request.form.get('type')
        txn.category    = request.form.get('category')
        txn.description = request.form.get('description', '').strip()
        db.session.commit()
        flash('Transaction updated successfully.')
        return redirect(url_for('main.dashboard'))
    return render_template('edit_transaction.html', txn=txn, total_income=inc, total_expense=exp, balance=bal)

@main.route('/delete/<int:id>')
@login_required
def delete_transaction(id):
    txn = Transaction.query.get_or_404(id)
    if txn.user_id == current_user.id:
        db.session.delete(txn)
        db.session.commit()
        flash('Transaction removed.')
    return redirect(url_for('main.dashboard'))

@main.route('/reports')
@login_required
def reports():
    from sqlalchemy import extract
    from datetime import timedelta
    monthly_data = []
    for i in range(5, -1, -1):
        d = datetime.now().replace(day=1) - timedelta(days=i*30)
        mi = db.session.query(db.func.sum(Transaction.amount)).filter(
            Transaction.user_id==current_user.id, Transaction.type=='income',
            extract('month', Transaction.date)==d.month,
            extract('year', Transaction.date)==d.year
        ).scalar() or 0
        me = db.session.query(db.func.sum(Transaction.amount)).filter(
            Transaction.user_id==current_user.id, Transaction.type=='expense',
            extract('month', Transaction.date)==d.month,
            extract('year', Transaction.date)==d.year
        ).scalar() or 0
        monthly_data.append({'month': d.strftime('%b'), 'income': float(mi), 'expense': float(me)})
    cats = db.session.query(
        Transaction.category,
        db.func.sum(Transaction.amount).label('total')
    ).filter_by(user_id=current_user.id, type='expense').group_by(Transaction.category).all()
    inc, exp, bal = get_totals(current_user.id)
    return render_template('reports.html',
        monthly_data=monthly_data, categories=cats,
        total_income=inc, total_expense=exp, balance=bal)

@main.route('/connect-whatsapp', methods=['POST'])
@login_required
def connect_whatsapp():
    raw = request.form.get('whatsapp_number', '').strip()
    number = ''.join(filter(str.isdigit, raw))
    if len(number) == 10:
        number = '91' + number
    elif number.startswith('0') and len(number) == 11:
        number = '91' + number[1:]
    elif not number.startswith('91'):
        number = '91' + number

    current_user.whatsapp = f'meta:{number}'
    db.session.commit()

    first = current_user.name.split()[0]
    welcome = (
        f"Hey {first}! Welcome to Ledgr 🎉\n\n"
        f"I'm your personal finance assistant — right here on WhatsApp.\n\n"
        f"*Log income:*\n"
        f"r 5000 salary\n"
        f"received 8000 freelance\n"
        f"+5000 client\n\n"
        f"*Log expense:*\n"
        f"s 300 food\n"
        f"spent 500 petrol\n"
        f"-1200 rent\n\n"
        f"*Any order works:*\n"
        f"mohit r 500 ✓\n"
        f"food s 300 ✓\n"
        f"500 r salary ✓\n\n"
        f"*Bulk (comma separated):*\n"
        f"r 20000 salary, s 800 food, s 300 auto\n\n"
        f"*Commands:*\n"
        f"b — balance\n"
        f"aaj — today's summary\n"
        f"week — this week\n"
        f"h — full guide\n\n"
        f"Your dashboard: ledgr.co.in 🌐\n\n"
        f"Ready when you are! 🚀"
    )
    send_whatsapp(number, welcome)
    flash('WhatsApp connected! Check your WhatsApp — a welcome message is on its way. 🎉')
    return redirect(url_for('main.dashboard'))

@main.route('/disconnect-whatsapp')
@login_required
def disconnect_whatsapp():
    current_user.whatsapp = None
    db.session.commit()
    flash('WhatsApp number removed.')
    return redirect(url_for('main.dashboard'))

# ══════════════════════════════════════════
# META WEBHOOK
# ══════════════════════════════════════════

@main.route('/meta-webhook', methods=['GET'])
def meta_verify():
    """Meta calls this to verify webhook"""
    cfg = get_cfg()
    mode      = request.args.get('hub.mode')
    token     = request.args.get('hub.verify_token')
    challenge = request.args.get('hub.challenge')
    if mode == 'subscribe' and token == cfg['verify']:
        print("[Webhook] ✅ Verified!")
        return challenge, 200
    print(f"[Webhook] ❌ Failed — token: {token}")
    return 'Forbidden', 403

@main.route('/meta-webhook', methods=['POST'])
def meta_webhook():
    """Handle incoming WhatsApp messages"""
    data = request.get_json(silent=True)
    if not data:
        return 'ok', 200

    try:
        entry   = data.get('entry', [{}])[0]
        changes = entry.get('changes', [{}])[0]
        value   = changes.get('value', {})

        # Only process message events
        if 'messages' not in value:
            return 'ok', 200

        message    = value['messages'][0]
        from_num   = message['from']
        message_id = message.get('id', '')
        msg_type   = message.get('type', 'text')

        print(f"[Webhook] Message from {from_num} type={msg_type}")
        mark_read(message_id)

        # Find user
        user = User.query.filter_by(whatsapp=f'meta:{from_num}').first()

        if not user:
            send_whatsapp(from_num,
                "👋 Hey! I'm the Ledgr bot.\n\n"
                "Your number isn't linked to any account yet.\n\n"
                "📱 Visit *ledgr.co.in* to:\n"
                "1. Create a free account\n"
                "2. Connect this WhatsApp number\n\n"
                "Then come back and start tracking! 🚀"
            )
            return 'ok', 200

        if msg_type == 'text':
            text = message.get('text', {}).get('body', '').strip()
            if text:
                _process_message(user, from_num, text)
        elif msg_type == 'image':
            send_whatsapp(from_num,
                "📸 Bill scanning is coming soon!\n\n"
                "For now, type the amount:\n"
                "Example: *s 1250 restaurant*"
            )
        else:
            send_whatsapp(from_num, "Please send a text message.\nType *h* for help.")

    except Exception as e:
        print(f"[Webhook] Error: {e}")
        import traceback
        traceback.print_exc()

    return 'ok', 200

# ══════════════════════════════════════════
# MESSAGE PROCESSOR
# ══════════════════════════════════════════

CATEGORY_MAP = {
    'Food':          ['food','lunch','dinner','breakfast','swiggy','zomato','restaurant',
                      'eat','chai','snack','khana','nashta','bhojan','dal','roti'],
    'Transport':     ['uber','ola','auto','cab','petrol','transport','travel','metro',
                      'bus','fuel','rapido','train','flight','rickshaw','rick'],
    'Salary':        ['salary','stipend','payroll','ctc','job','naukri','mahina'],
    'Freelance':     ['freelance','client','project','design','dev','work','gig','kaam'],
    'Bills':         ['bill','electricity','wifi','recharge','phone','internet',
                      'broadband','rent','emi','bijli','paani','gas','light'],
    'Shopping':      ['amazon','flipkart','shop','bought','purchase','clothes',
                      'myntra','kapde','kharida','meesho'],
    'Health':        ['doctor','medicine','hospital','pharmacy','gym','health',
                      'medical','dawai','dawa','clinic'],
    'Investment':    ['invest','sip','mutual','stock','shares','crypto','fd','ppf','savings'],
    'Entertainment': ['movie','netflix','spotify','game','fun','party','prime',
                      'hotstar','film','show'],
    'Business':      ['business','revenue','sales','dukan','store','profit'],
    'Udhaar':        ['udhaar','udhar','borrow','lend','debt','baaki','baki'],
}

INCOME_WORDS = {
    'r','rec','received','income','i','credit','cr','got','earned',
    'in','rcv','receive','mila','aaya','aaye','mil','payment','liya','le','li'
}
EXPENSE_WORDS = {
    's','sp','spent','expense','e','debit','dr','paid','pay','bought',
    'out','ex','spend','diye','diya','kiya','kharcha','gaya','de','dia','kharche'
}

def detect_category(words, txn_type):
    joined = ' '.join(words).lower()
    for cat, kws in CATEGORY_MAP.items():
        if any(kw in joined for kw in kws):
            return cat
    return 'Other Income' if txn_type == 'income' else 'Other Expense'

def parse_entry(raw):
    """
    Ultra-flexible parser — any order, any format:
    r 5000 salary | mohit r 500 | 500 food s | +5000 | -300 food | 5k r
    """
    parts = raw.strip().split()
    if not parts:
        return None

    txn_type   = None
    amount     = None
    desc_parts = []

    for part in parts:
        low = part.lower()

        # +/- prefix with number attached e.g. +5000 -300
        if (low.startswith('+') or low.startswith('-')) and len(low) > 1:
            txn_type = 'income' if low.startswith('+') else 'expense'
            num = low[1:].replace(',','').replace('k','000').replace('K','000')
            try:
                amount = float(num)
            except:
                desc_parts.append(part[1:])
            continue

        # Standalone type keywords
        if low in INCOME_WORDS:  txn_type = 'income';  continue
        if low in EXPENSE_WORDS: txn_type = 'expense'; continue
        if low == '+':           txn_type = 'income';  continue
        if low == '-':           txn_type = 'expense'; continue

        # Amount — supports 5k, 1.5k, 5,000, 5000
        num = low.replace(',','').replace('k','000').replace('K','000')
        try:
            amount = float(num)
            continue
        except:
            pass

        desc_parts.append(part)

    if not txn_type or not amount or amount <= 0:
        return None

    cat  = detect_category(desc_parts, txn_type)
    desc = ' '.join(desc_parts).strip().capitalize() or cat
    return {'type': txn_type, 'amount': amount, 'category': cat, 'description': desc}

def _process_message(user, from_num, text):
    t = text.strip().lower()

    # ── BALANCE ──
    if t in ['b','bal','balance','total','kitna','kitna hai','balance batao','hisaab']:
        inc, exp, bal = get_totals(user.id)
        e = "✅" if bal >= 0 else "⚠️"
        send_whatsapp(from_num,
            f"📊 *Ledgr Balance*\n\n"
            f"💰 Income:   ₹{inc:,.0f}\n"
            f"💸 Expense:  ₹{exp:,.0f}\n"
            f"────────────────\n"
            f"{e} Balance:  ₹{bal:,.0f}"
        )
        return

    # ── HELP ──
    if t in ['h','help','?','guide','commands','start','menu']:
        send_whatsapp(from_num,
            "📖 *Ledgr Guide*\n\n"
            "*Income:*\n"
            "r 5000 salary\n"
            "received 8000 client\n"
            "+5000 freelance\n\n"
            "*Expense:*\n"
            "s 300 food\n"
            "spent 500 petrol\n"
            "-1200 rent\n\n"
            "*Any order works:*\n"
            "mohit r 500 ✓\n"
            "food s 300 ✓\n"
            "500 r salary ✓\n\n"
            "*Bulk — comma:*\n"
            "r 20000 salary, s 800 food, s 300 auto\n\n"
            "*5k = 5000:*\n"
            "r 20k salary ✓\n\n"
            "*Commands:*\n"
            "b — balance\n"
            "aaj — today's summary\n"
            "week — this week\n"
            "h — this guide\n\n"
            "Dashboard: ledgr.co.in 🌐"
        )
        return

    # ── TODAY ──
    if t in ['aaj','today','aaj ka','aaj ka hisaab','aaj batao']:
        from datetime import date
        today = date.today()
        txns = Transaction.query.filter(
            Transaction.user_id == user.id,
            db.func.date(Transaction.date) == today
        ).order_by(Transaction.date.desc()).all()
        if not txns:
            send_whatsapp(from_num,
                f"📭 *{today.strftime('%d %b')}* — No entries yet.\n\n"
                "Log karo:\n*s 50 chai* ya *r 5000 salary*"
            )
            return
        inc = sum(t.amount for t in txns if t.type=='income')
        exp = sum(t.amount for t in txns if t.type=='expense')
        lines = [f"📊 *Today — {today.strftime('%d %b')}*\n"]
        for txn in txns[-8:]:  # last 8
            e = '💰' if txn.type=='income' else '💸'
            lines.append(f"{e} ₹{txn.amount:,.0f} — {txn.description or txn.category}")
        if inc: lines.append(f"\n💰 In:  +₹{inc:,.0f}")
        if exp: lines.append(f"💸 Out: -₹{exp:,.0f}")
        lines.append(f"⚡ Net: ₹{inc-exp:,.0f}")
        send_whatsapp(from_num, '\n'.join(lines))
        return

    # ── WEEK ──
    if t in ['week','hafte','is hafte','weekly','week ka','week batao']:
        from datetime import timedelta, date
        today = date.today()
        week_start = today - timedelta(days=today.weekday())
        txns = Transaction.query.filter(
            Transaction.user_id == user.id,
            db.func.date(Transaction.date) >= week_start
        ).all()
        if not txns:
            send_whatsapp(from_num, "📭 No entries this week yet.")
            return
        inc = sum(t.amount for t in txns if t.type=='income')
        exp = sum(t.amount for t in txns if t.type=='expense')
        send_whatsapp(from_num,
            f"📊 *This Week*\n"
            f"{week_start.strftime('%d %b')} – {today.strftime('%d %b')}\n\n"
            f"💰 Income:  ₹{inc:,.0f}\n"
            f"💸 Expense: ₹{exp:,.0f}\n"
            f"⚡ Net:     ₹{inc-exp:,.0f}\n\n"
            f"Total entries: {len(txns)}"
        )
        return

    # ── PARSE TRANSACTIONS ──
    raw_entries = [e.strip() for e in text.split(',') if e.strip()]
    results, errors = [], []

    for raw in raw_entries:
        parsed = parse_entry(raw)
        if parsed:
            txn = Transaction(
                user_id=user.id,
                type=parsed['type'],
                amount=parsed['amount'],
                category=parsed['category'],
                description=parsed['description'],
                date=datetime.now()
            )
            db.session.add(txn)
            results.append(parsed)
        else:
            errors.append(raw)

    if results:
        db.session.commit()

    if not results:
        send_whatsapp(from_num,
            "🤔 Samajh nahi aaya. Try karo:\n\n"
            "*r 5000 salary*\n"
            "*s 300 food*\n"
            "*r 20000 salary, s 800 food*\n\n"
            "Type *h* for guide."
        )
        return

    _, __, bal = get_totals(user.id)

    if len(results) == 1:
        r = results[0]
        e = '💰' if r['type']=='income' else '💸'
        a = '+' if r['type']=='income' else '-'
        send_whatsapp(from_num,
            f"{e} *Recorded!*\n\n"
            f"{a}₹{r['amount']:,.0f} — {r['description']}\n"
            f"📁 {r['category']}\n\n"
            f"Balance: ₹{bal:,.0f}"
        )
    else:
        ti = sum(r['amount'] for r in results if r['type']=='income')
        te = sum(r['amount'] for r in results if r['type']=='expense')
        lines = [f"✅ *{len(results)} entries recorded!*\n"]
        for r in results:
            e = '💰' if r['type']=='income' else '💸'
            lines.append(f"{e} ₹{r['amount']:,.0f} — {r['description']}")
        if ti: lines.append(f"\n💰 Total in:  +₹{ti:,.0f}")
        if te: lines.append(f"💸 Total out: -₹{te:,.0f}")
        lines.append(f"⚡ Balance: ₹{bal:,.0f}")
        if errors: lines.append(f"\n⚠️ Skipped: {', '.join(errors)}")
        send_whatsapp(from_num, '\n'.join(lines))