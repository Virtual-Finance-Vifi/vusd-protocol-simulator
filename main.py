from flask import Flask, render_template, request, redirect, url_for
from models import db, User, Config, initialize_db, LiquidityPool


def calculate_protocol_rate():
    vkes_supply = sum([u.vkes_balance for u in User.query.all()])
    vrqt_supply = sum([u.vrqt_balance for u in User.query.all()])
    protocol_rate = vkes_supply / vrqt_supply if vrqt_supply != 0 else 1
    return protocol_rate


def calculate_total_supplies():
    total_vusd = sum([u.vusd_balance for u in User.query.all()])
    total_vkes = sum([u.vkes_balance for u in User.query.all()])
    total_vrqt = sum([u.vrqt_balance for u in User.query.all()])

    return total_vusd, total_vkes, total_vrqt


def create_app():
    app = Flask(__name__)
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///site.db'
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

    db.init_app(app)

    with app.app_context():
        db.create_all()
        initialize_db()

    @app.route('/')
    def index():
        users = User.query.all()
        pools = LiquidityPool.query.all()
        total_vusd, total_vkes, total_vrqt = calculate_total_supplies()
        oracle_rate = Config.get_oracle_rate()
        protocol_rate = calculate_protocol_rate()
        config = Config.query.first()
        
        # Calculate new ratios
        flux_ratio = 1 if total_vrqt == 0 else protocol_rate / oracle_rate if oracle_rate != 0 else 1
        reserve_ratio = config.vusd_burnt_supply / total_vrqt if total_vrqt != 0 else 1
        flux_influence = 1.0 if (flux_ratio > 1 and reserve_ratio <= 1) else flux_ratio

        return render_template('index.html',
                             users=users,
                             pools=pools,
                             total_vusd=total_vusd,
                             total_vkes=total_vkes,
                             total_vrqt=total_vrqt,
                             vusd_burnt=config.vusd_burnt_supply,
                             oracle_rate=oracle_rate,
                             protocol_rate=protocol_rate,
                             flux_ratio=flux_ratio,
                             reserve_ratio=reserve_ratio,
                             flux_influence=flux_influence)

    @app.route('/set_oracle_rate', methods=['POST'])
    def set_oracle_rate():
        new_rate = float(request.form.get('oracle_rate'))
        Config.set_oracle_rate(new_rate)
        return redirect(url_for('index'))

    @app.route('/transfer', methods=['POST'])
    def transfer_asset():
        from_user = request.form.get('from_user')
        to_user = request.form.get('to_user')
        asset = request.form.get('asset')
        amount = float(request.form.get('amount'))

        # Fetch the user who is transferring the asset
        sender = User.query.get(from_user)

        if not sender or getattr(sender, f"{asset}_balance", 0) < amount:
            # Redirect with an error if insufficient funds
            return redirect(
                url_for('index', error="Insufficient balance for transfer"))

        # Perform the transfer
        User.transfer_asset(from_user, to_user, asset, amount)
        return redirect(url_for('index'))

    @app.route('/convert', methods=['POST'])
    def convert_vusd():
        user_id = request.form.get('user_id')
        amount = float(request.form.get('amount'))
        oracle_rate = Config.get_oracle_rate()

        # Fetch the user performing the conversion
        user = User.query.get(user_id)

        if not user or user.vusd_balance < amount:
            # Redirect with an error if insufficient vUSD balance
            return redirect(
                url_for('index',
                        error="Insufficient vUSD balance for conversion"))

        # Perform the conversion
        User.convert_vusd(user_id, amount, oracle_rate)
        return redirect(url_for('index'))

    @app.route('/convert_back', methods=['POST'])
    def convert_back_to_vusd():
        user_id = request.form.get('user_id')
        amount = float(request.form.get('amount'))

        # Fetch the user performing the conversion
        user = User.query.get(user_id)

        if not user or user.vkes_balance < amount:
            # Redirect with an error if insufficient vKES balance
            return redirect(
                url_for('index',
                        error="Insufficient vKES balance for conversion"))

        # Perform the conversion
        success = User.convert_back_to_vusd(user_id, amount)
        if not success:
            return redirect(
                url_for('index', error="Insufficient balance to convert"))

        return redirect(url_for('index'))

    @app.route('/pool/create', methods=['POST'])
    def create_pool():
        user_id = request.form.get('user_id')
        vkes_amount = float(request.form.get('vkes_amount'))
        vrqt_amount = float(request.form.get('vrqt_amount'))
        lock_days = int(request.form.get('lock_days', 7))
        
        user = User.query.get(user_id)
        if not user:
            return redirect(url_for('index', error="User not found"))
        
        pool = user.provide_liquidity(vkes_amount, vrqt_amount)
        if not pool:
            return redirect(url_for('index', error="Insufficient balance for pool creation"))
        
        return redirect(url_for('index'))

    @app.route('/pool/withdraw/<int:pool_id>', methods=['POST'])
    def withdraw_pool(pool_id):
        user_id = request.form.get('user_id')
        user = User.query.get(user_id)
        
        if not user:
            return redirect(url_for('index', error="User not found"))
        
        success = user.withdraw_liquidity(pool_id)
        if not success:
            return redirect(url_for('index', error="Cannot withdraw: pool is locked or doesn't exist"))
        
        return redirect(url_for('index'))

    @app.route('/pool/swap', methods=['POST'])
    def swap_assets():
        user_id = request.form.get('user_id')
        pool_id = int(request.form.get('pool_id'))
        asset = request.form.get('asset')
        amount = float(request.form.get('amount'))
        
        user = User.query.get(user_id)
        if not user:
            return redirect(url_for('index', error="User not found"))
        
        received = user.perform_swap(pool_id, asset, amount)
        if received == 0:
            return redirect(url_for('index', error=f"Swap failed. Insufficient {asset.upper()} balance or pool liquidity"))
        
        return redirect(url_for('index', message=f"Swap successful. Received {received:.2f} {asset.upper()}"))

    @app.route('/yield/calculate', methods=['POST'])
    def calculate_yields():
        """Calculate yields for all locked positions"""
        users = User.query.all()
        for user in users:
            user.calculate_yield()
        return redirect(url_for('index'))

    return app


if __name__ == '__main__':
    app = create_app()
    app.run(debug=True, host='0.0.0.0', port=8080)
