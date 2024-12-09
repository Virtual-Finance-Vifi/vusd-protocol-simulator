from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()


class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), unique=True, nullable=False)
    vusd_balance = db.Column(db.Float, default=0)
    vkes_balance = db.Column(db.Float, default=0)
    vrqt_balance = db.Column(db.Float, default=0)

    @classmethod
    def transfer_asset(cls, from_user_id, to_user_id, asset, amount):
        from_user = cls.query.filter_by(id=from_user_id).first()
        to_user = cls.query.filter_by(id=to_user_id).first()
        if from_user and to_user:
            if asset == 'vusd':
                from_user.vusd_balance -= amount
                to_user.vusd_balance += amount
            elif asset == 'vkes':
                from_user.vkes_balance -= amount
                to_user.vkes_balance += amount
            elif asset == 'vrqt':
                from_user.vrqt_balance -= amount
                to_user.vrqt_balance += amount

            db.session.commit()

    @classmethod
    def convert_vusd(cls, user_id, amount, oracle_rate):
        user = cls.query.filter_by(id=user_id).first()
        if user:
            # Calculate total supplies
            vrqt_supply = sum([u.vrqt_balance for u in cls.query.all()])
            vkes_supply = sum([u.vkes_balance for u in cls.query.all()])
            
            # Calculate ratios
            protocol_rate = vkes_supply / vrqt_supply if vrqt_supply != 0 else 1
            # If vrqt_supply is 0, flux_ratio should be 1
            flux_ratio = 1 if vrqt_supply == 0 else protocol_rate / oracle_rate if oracle_rate != 0 else 1
            
            # Get current burnt supply from config
            config = Config.query.first()
            reserve_ratio = config.vusd_burnt_supply / vrqt_supply if vrqt_supply != 0 else 1
            
            # Calculate flux influence
            flux_influence = 1.0 if (flux_ratio > 1 and reserve_ratio <= 1) else flux_ratio
            
            # Update balances
            user.vusd_balance -= amount
            user.vkes_balance += amount * oracle_rate
            user.vrqt_balance += amount * flux_influence

            # Update the burnt supply
            config.vusd_burnt_supply += amount
            db.session.commit()

    @classmethod
    def convert_back_to_vusd(cls, user_id, vusd_entered):
        user = cls.query.filter_by(id=user_id).first()
        if user:
            vkes_supply = sum([u.vkes_balance for u in cls.query.all()])
            vrqt_supply = sum([u.vrqt_balance for u in cls.query.all()])
            protocol_rate = vkes_supply / vrqt_supply if vrqt_supply != 0 else 1

            vkes_needed = vusd_entered * protocol_rate
            vrqt_needed = vusd_entered

            if user.vkes_balance >= vkes_needed and user.vrqt_balance >= vrqt_needed:
                user.vkes_balance -= vkes_needed
                user.vrqt_balance -= vrqt_needed
                user.vusd_balance += vusd_entered

                # Update the burnt supply
                config = Config.query.first()
                config.vusd_burnt_supply -= vusd_entered  # Decrease burnt VUSD
                db.session.commit()
                return True
            else:
                return False


class Config(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    oracle_rate = db.Column(db.Float, default=128.0)
    vusd_burnt_supply = db.Column(db.Float,
                                  default=0.0)  # Track VUSD burnt supply

    @classmethod
    def get_oracle_rate(cls):
        config = cls.query.first()
        if not config:
            config = cls(oracle_rate=128.0,
                         vusd_burnt_supply=0.0)  # Initialize with burnt supply
            db.session.add(config)
            db.session.commit()
        return config.oracle_rate

    @classmethod
    def set_oracle_rate(cls, new_rate):
        config = cls.query.first()
        if not config:
            config = cls()
            db.session.add(config)
        config.oracle_rate = new_rate
        db.session.commit()


def initialize_db():
    db.drop_all()
    db.create_all()

    # Initialize the Config if not already set
    config = Config.query.first()
    if not config:
        config = Config(oracle_rate=128.0, vusd_burnt_supply=0.0)
        db.session.add(config)

    # Add initial users
    alice = User(name='Alice', vusd_balance=1000)
    bob = User(name='Bob', vusd_balance=500)
    db.session.add_all([alice, bob])

    db.session.commit()
