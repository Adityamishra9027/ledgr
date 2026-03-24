from flask import Blueprint, render_template, redirect, url_for, request, flash
from flask_login import login_user, logout_user, login_required, current_user
from app import db
from app.models import User, Transaction
from datetime import datetime
from twilio.twiml.messaging_response import MessagingResponse

main = Blueprint('main', __name__)

# ── GREETING HELPERS ──
def get_greeting():
    hour = datetime.now().hour
    if 5 <= hour < 12:
        return "Good Morning"
    elif 12 <= hour < 17:
        return "Good Afternoon"
    elif 17 <= hour < 21:
        return "Good Evening"
    else:
        return "Night Owl"

def get_greeting_sub():
    hour = datetime.now().hour
    if 5 <= hour < 12:
        return "Here's your financial overview to start the day."
    elif 12 <= hour < 17:
        return "Your finances are looking sharp. Here's where things stand."
    elif 17 <= hour < 21:
        return "Winding down? Here's a summary of your day's activity."
    else:
        return "Burning the midnight oil? Your finances are right here."

# ── ROUTES ──
@main.route('/')
def index():
    if current_user.is_authenticated:
        return redirect(url_for('main.dashboard'))
    return redirect(url_for('main.login'))

@main.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        name = request.form.get('name')
        email = request.form.get('email')
        password = request.form.get('password')
        user = User.query.filter_by(email=email).first()
        if user:
            flash('An account with this email already exists.')
            return redirect(url_for('main.register'))
        new_user = User(name=name, email=email)
        new_user.set_password(password)
        db.session.add(new_user)
        db.session.commit()
        flash('Account created. Welcome to Ledgr.')
        return redirect(url_for('main.login'))
    return render_template('register.html')

@main.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        user = User.query.filter_by(email=email).first()
        if user and user.check_password(password):
            login_user(user)
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
    transactions = Transaction.query.filter_by(
        user_id=current_user.id
    ).order_by(Transaction.date.desc()).limit(10).all()

    total_income = db.session.query(
        db.func.sum(Transaction.amount)
    ).filter_by(user_id=current_user.id, type='income').scalar() or 0

    total_expense = db.session.query(
        db.func.sum(Transaction.amount)
    ).filter_by(user_id=current_user.id, type='expense').scalar() or 0

    balance = total_income - total_expense

    return render_template('dashboard.html',
        transactions=transactions,
        total_income=total_income,
        total_expense=total_expense,
        balance=balance,
        greeting=get_greeting(),
        greeting_sub=get_greeting_sub()
    )

@main.route('/add', methods=['GET', 'POST'])
@login_required
def add_transaction():
    if request.method == 'POST':
        txn = Transaction(
            user_id=current_user.id,
            type=request.form.get('type'),
            amount=float(request.form.get('amount')),
            category=request.form.get('category'),
            description=request.form.get('description'),
            date=datetime.now()
        )
        db.session.add(txn)
        db.session.commit()
        flash('Transaction recorded successfully.')
        return redirect(url_for('main.dashboard'))
    return render_template('add_transaction.html')

@main.route('/delete/<int:id>')
@login_required
def delete_transaction(id):
    txn = Transaction.query.get_or_404(id)
    if txn.user_id == current_user.id:
        db.session.delete(txn)
        db.session.commit()
        flash('Transaction removed.')
    return redirect(url_for('main.dashboard'))

@main.route('/connect-whatsapp', methods=['POST'])
@login_required
def connect_whatsapp():
    number = request.form.get('whatsapp_number', '').strip()
    if not number.startswith('+'):
        number = '+91' + number
    current_user.whatsapp = f'whatsapp:{number}'
    db.session.commit()
    flash('WhatsApp connected successfully.')
    return redirect(url_for('main.dashboard'))

# ── WHATSAPP WEBHOOK ──
@main.route('/whatsapp', methods=['POST'])
def whatsapp_webhook():
    incoming = request.form.get('Body', '').strip()
    from_number = request.form.get('From', '')
    resp = MessagingResponse()
    msg = resp.message()

    user = User.query.filter_by(whatsapp=from_number).first()
    if not user:
        msg.body("Your number isn't linked to any Ledgr account.\nVisit your dashboard to connect WhatsApp.")
        return str(resp)

    text = incoming.strip()

    # ── BALANCE CHECK ──
    if text.lower() in ['b', 'bal', 'balance', 'total']:
        total_income = db.session.query(
            db.func.sum(Transaction.amount)
        ).filter_by(user_id=user.id, type='income').scalar() or 0
        total_expense = db.session.query(
            db.func.sum(Transaction.amount)
        ).filter_by(user_id=user.id, type='expense').scalar() or 0
        balance = total_income - total_expense
        msg.body(
            f"*📊 Ledgr Summary*\n\n"
            f"💰 Income:   ₹{total_income:,.0f}\n"
            f"💸 Expense:  ₹{total_expense:,.0f}\n"
            f"⚡ Balance:  ₹{balance:,.0f}"
        )
        return str(resp)

    # ── HELP ──
    if text.lower() in ['h', 'help', '?']:
        msg.body(
            "*📖 Ledgr Quick Guide*\n\n"
            "*Single entry:*\n"
            "r 5000 salary\n"
            "s 300 food\n\n"
            "*Bulk (comma separated):*\n"
            "r 20000 salary, s 800 food, r 5000 freelance\n\n"
            "*Any order works:*\n"
            "mohit r 500\n"
            "500 r mohit\n"
            "r mohit 500\n\n"
            "*Shortcuts:*\n"
            "r / + = income\n"
            "s / - = expense\n"
            "b = balance\n"
            "h = this help\n\n"
            "*Auto-detected categories:*\n"
            "food, transport, salary, freelance,\n"
            "bills, shopping, health, entertainment"
        )
        return str(resp)

    # ── CATEGORY MAP ──
    category_map = {
        'Food':          ['food', 'lunch', 'dinner', 'breakfast', 'swiggy', 'zomato', 'restaurant', 'eat', 'chai', 'tea', 'snack'],
        'Transport':     ['uber', 'ola', 'auto', 'cab', 'petrol', 'transport', 'travel', 'metro', 'bus', 'fuel', 'rapido'],
        'Salary':        ['salary', 'stipend', 'payroll', 'ctc', 'job'],
        'Freelance':     ['freelance', 'client', 'project', 'design', 'dev', 'work', 'gig'],
        'Bills':         ['bill', 'electricity', 'wifi', 'recharge', 'phone', 'internet', 'broadband', 'rent', 'emi'],
        'Shopping':      ['amazon', 'flipkart', 'shop', 'bought', 'purchase', 'clothes', 'myntra', 'meesho'],
        'Health':        ['doctor', 'medicine', 'hospital', 'pharmacy', 'gym', 'health', 'medical'],
        'Investment':    ['invest', 'sip', 'mutual', 'stock', 'shares', 'crypto', 'fd', 'ppf'],
        'Entertainment': ['movie', 'netflix', 'spotify', 'game', 'fun', 'party', 'prime', 'hotstar'],
        'Business':      ['business', 'revenue', 'sales'],
    }

    def detect_category(words, txn_type):
        joined = ' '.join(words).lower()
        for cat, keywords in category_map.items():
            if any(kw in joined for kw in keywords):
                return cat
        return 'Other Income' if txn_type == 'income' else 'Other Expense'

    # ── FLEXIBLE PARSER ──
    # Works regardless of order: r mohit 100 / mohit r 100 / 100 mohit r / mohit 100 r
    income_words  = {'r', 'rec', 'received', 'income', 'i', 'credit', 'cr', 'got', 'earned', 'in', 'rcv', 'receive'}
    expense_words = {'s', 'sp', 'spent', 'expense', 'e', 'debit', 'dr', 'paid', 'pay', 'bought', 'out', 'ex', 'spend'}

    def parse_entry(entry):
        parts = entry.strip().split()
        if not parts:
            return None

        txn_type = None
        amount   = None
        desc_parts = []

        for part in parts:
            low = part.lower()

            # +/- prefix directly on a word like "+5000" or "-300"
            if low.startswith('+') and len(low) > 1:
                txn_type = 'income'
                num_str = low[1:].replace(',', '').replace('k', '000')
                try:
                    amount = float(num_str)
                except ValueError:
                    desc_parts.append(part[1:])
                continue

            if low.startswith('-') and len(low) > 1:
                txn_type = 'expense'
                num_str = low[1:].replace(',', '').replace('k', '000')
                try:
                    amount = float(num_str)
                except ValueError:
                    desc_parts.append(part[1:])
                continue

            # Type keyword
            if low in income_words:
                txn_type = 'income'
                continue
            if low in expense_words:
                txn_type = 'expense'
                continue

            # Bare + or - as standalone word
            if low == '+':
                txn_type = 'income'
                continue
            if low == '-':
                txn_type = 'expense'
                continue

            # Amount?
            num_str = low.replace(',', '').replace('k', '000')
            try:
                amount = float(num_str)
                continue
            except ValueError:
                pass

            # Everything else = description
            desc_parts.append(part)

        # Must have both type and amount
        if not txn_type or not amount:
            return None

        category    = detect_category(desc_parts, txn_type)
        description = ' '.join(desc_parts).strip().capitalize() or category

        return {
            'type':        txn_type,
            'amount':      amount,
            'category':    category,
            'description': description,
        }

    # ── SPLIT BY COMMA FOR BULK ──
    raw_entries = [e.strip() for e in text.split(',') if e.strip()]

    results = []
    errors  = []

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

    # ── REPLY ──
    if not results:
        msg.body(
            "Couldn't understand that. Try:\n\n"
            "r 5000 salary\n"
            "s 300 food\n"
            "mohit r 500\n"
            "r 20000 salary, s 800 food, r 5000 client\n\n"
            "Type *h* for full guide."
        )
        return str(resp)

    if len(results) == 1:
        r = results[0]
        emoji = '💰' if r['type'] == 'income' else '💸'
        msg.body(
            f"{emoji} *Recorded*\n\n"
            f"{'Income' if r['type'] == 'income' else 'Expense'}:   ₹{r['amount']:,.0f}\n"
            f"Category:  {r['category']}\n"
            f"Note:      {r['description']}"
        )
    else:
        total_in = sum(r['amount'] for r in results if r['type'] == 'income')
        total_ex = sum(r['amount'] for r in results if r['type'] == 'expense')
        lines = [f"*✅ {len(results)} transactions recorded*\n"]
        for r in results:
            e = '💰' if r['type'] == 'income' else '💸'
            lines.append(f"{e} ₹{r['amount']:,.0f}  —  {r['description']}")
        if total_in:
            lines.append(f"\n💰 Total in:   +₹{total_in:,.0f}")
        if total_ex:
            lines.append(f"💸 Total out:  -₹{total_ex:,.0f}")
        if errors:
            lines.append(f"\n⚠️ Could not parse: {', '.join(errors)}")
        msg.body('\n'.join(lines))

    return str(resp)