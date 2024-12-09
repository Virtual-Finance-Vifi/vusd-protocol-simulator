from flask_sqlalchemy import SQLAlchemy
from datetime import datetime, timedelta

db = SQLAlchemy()


class LiquidityPool(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    vkes_balance = db.Column(db.Float, default=0)
    vrqt_balance = db.Column(db.Float, default=0)
    lock_time = db.Column(db.DateTime)
    fee_percentage = db.Column(db.Float, default=0.003)  # 0.3% fee
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    @classmethod
    def create_pool(cls, vkes_amount: float, vrqt_amount: float, user_id: int, lock_days: int = 7):
        pool = cls(
            vkes_balance=vkes_amount,
            vrqt_balance=vrqt_amount,
            lock_time=datetime.now() + timedelta(days=lock_days),
            user_id=user_id
        )
        db.session.add(pool)
        db.session.commit()
        return pool

    def swap_vrqt_to_vkes(self, vrqt_amount: float) -> float:
        fee = vrqt_amount * self.fee_percentage
        vrqt_after_fee = vrqt_amount - fee
        
        # Calculate vKES output using constant product formula
        k = self.vkes_balance * self.vrqt_balance
        new_vrqt = self.vrqt_balance + vrqt_after_fee
        new_vkes = k / new_vrqt
        vkes_out = self.vkes_balance - new_vkes
        
        # Update pool balances
        self.vrqt_balance = new_vrqt
        self.vkes_balance = new_vkes
        db.session.commit()
        
        return vkes_out

    def swap_vkes_to_vrqt(self, vkes_amount: float) -> float:
        fee = vkes_amount * self.fee_percentage
        vkes_after_fee = vkes_amount - fee
        
        # Calculate vRQT output using constant product formula
        k = self.vkes_balance * self.vrqt_balance
        new_vkes = self.vkes_balance + vkes_after_fee
        new_vrqt = k / new_vkes
        vrqt_out = self.vrqt_balance - new_vrqt
        
        # Update pool balances
        self.vkes_balance = new_vkes
        self.vrqt_balance = new_vrqt
        db.session.commit()
        
        return vrqt_out

    def is_locked(self) -> bool:
        return datetime.now() < self.lock_time
        
    def get_pool_value(self) -> float:
        """Calculate total pool value in vUSD terms"""
        return self.vrqt_balance  # 1:1 with vUSD


class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), unique=True, nullable=False)
    vusd_balance = db.Column(db.Float, default=0)
    vkes_balance = db.Column(db.Float, default=0)
    vrqt_balance = db.Column(db.Float, default=0)
    pool = db.relationship('LiquidityPool', backref='user', lazy=True)
    pool_vkes = db.Column(db.Float, default=0)  # Locked in pool
    pool_vrqt = db.Column(db.Float, default=0)  # Locked in pool
    yield_vusd = db.Column(db.Float, default=0)  # Accumulated yield

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

    def provide_liquidity(self, vkes_amount: float, vrqt_amount: float) -> LiquidityPool:
        if self.vkes_balance >= vkes_amount and self.vrqt_balance >= vrqt_amount:
            # Create pool with user_id
            pool = LiquidityPool.create_pool(
                vkes_amount=vkes_amount,
                vrqt_amount=vrqt_amount,
                user_id=self.id
            )
            
            # Update user balances
            self.vkes_balance -= vkes_amount
            self.vrqt_balance -= vrqt_amount
            self.pool_vkes += vkes_amount
            self.pool_vrqt += vrqt_amount
            
            db.session.commit()
            return pool
        return None

    def calculate_yield(self, apy: float = 0.05):
        """Calculate weekly yield based on locked assets"""
        weekly_rate = apy / 52
        total_locked_value = self.pool_vrqt  # Assuming 1:1 with USD
        self.yield_vusd += total_locked_value * weekly_rate
        db.session.commit()

    def withdraw_liquidity(self, pool_id: int) -> bool:
        """Withdraw liquidity from a pool after lock period"""
        pool = LiquidityPool.query.get(pool_id)
        if not pool or datetime.now() < pool.lock_time:
            return False
            
        # Return assets to user
        self.vkes_balance += pool.vkes_balance
        self.vrqt_balance += pool.vrqt_balance
        
        # Clear pool balances
        self.pool_vkes -= pool.vkes_balance
        self.pool_vrqt -= pool.vrqt_balance
        
        # Delete pool
        db.session.delete(pool)
        db.session.commit()
        return True
        
    def perform_swap(self, pool_id: int, asset: str, amount: float) -> float:
        """Perform swap in liquidity pool"""
        pool = LiquidityPool.query.get(pool_id)
        if not pool:
            return 0
            
        if asset == 'vrqt' and self.vrqt_balance >= amount:
            self.vrqt_balance -= amount
            vkes_received = pool.swap_vrqt_to_vkes(amount)
            self.vkes_balance += vkes_received
            db.session.commit()
            return vkes_received
            
        elif asset == 'vkes' and self.vkes_balance >= amount:
            self.vkes_balance -= amount
            vrqt_received = pool.swap_vkes_to_vrqt(amount)
            self.vrqt_balance += vrqt_received
            db.session.commit()
            return vrqt_received
            
        return 0


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
