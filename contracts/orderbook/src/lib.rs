#![no_std]

use soroban_sdk::{contract, contractimpl, token, Address, Env};

mod events;
mod storage;
mod types;

use types::Asset;

#[contract]
pub struct OrderBookContract;

#[contractimpl]
impl OrderBookContract {
    /// Constructor: Initialize the order book contract with admin and two token contracts.
    /// Called automatically during contract deployment.
    ///
    /// # Arguments
    /// * `admin` - The admin address that will authorize withdrawals and settlements
    /// * `asset_a` - Token contract address for asset A
    /// * `asset_b` - Token contract address for asset B
    pub fn __constructor(env: Env, admin: Address, asset_a: Address, asset_b: Address) {
        storage::set_admin(&env, &admin);
        storage::set_asset_a(&env, &asset_a);
        storage::set_asset_b(&env, &asset_b);
        storage::extend_instance_ttl(&env);
    }

    /// Deposit tokens into the order book.
    ///
    /// The user must have previously approved this contract to transfer tokens.
    /// Emits a deposit event that the backend listens to.
    ///
    /// # Arguments
    /// * `user` - The user depositing tokens
    /// * `asset` - Which asset to deposit (A or B)
    /// * `amount` - Amount to deposit (must be positive)
    ///
    /// # Panics
    /// Panics if amount is not positive or if token transfer fails
    pub fn deposit(env: Env, user: Address, asset: Asset, amount: i128) {
        // User must authorize the deposit
        user.require_auth();

        if amount <= 0 {
            panic!("Amount must be positive");
        }

        storage::extend_instance_ttl(&env);

        // Get the token contract address
        let token_address = storage::get_asset_address(&env, asset);
        let token_client = token::Client::new(&env, &token_address);

        // Transfer tokens from user to this contract
        let contract_address = env.current_contract_address();
        token_client.transfer(&user, &contract_address, &amount);

        // Update user's balance
        storage::increase_balance(&env, &user, asset, amount);

        // Emit deposit event for the backend to track
        events::emit_deposit(&env, &user, asset, amount);
    }

    /// Withdraw tokens from the order book.
    ///
    /// Only the admin can authorize withdrawals. The backend checks that the user
    /// has no outstanding liabilities before requesting a withdrawal.
    ///
    /// # Arguments
    /// * `user` - The user withdrawing tokens
    /// * `asset` - Which asset to withdraw (A or B)
    /// * `amount` - Amount to withdraw (must be positive)
    ///
    /// # Panics
    /// Panics if amount is not positive, user has insufficient balance,
    /// or admin doesn't authorize
    pub fn withdraw(env: Env, user: Address, asset: Asset, amount: i128) {
        // Admin must authorize withdrawals
        let admin = storage::get_admin(&env);
        admin.require_auth();

        if amount <= 0 {
            panic!("Amount must be positive");
        }

        storage::extend_instance_ttl(&env);

        // Decrease user's balance (will panic if insufficient)
        storage::decrease_balance(&env, &user, asset, amount);

        // Transfer tokens from contract to user
        let token_address = storage::get_asset_address(&env, asset);
        let token_client = token::Client::new(&env, &token_address);
        let contract_address = env.current_contract_address();
        token_client.transfer(&contract_address, &user, &amount);

        // Emit withdraw event
        events::emit_withdraw(&env, &user, asset, amount);
    }

    /// Settle a trade between two users.
    ///
    /// Only the admin can authorize settlements. The backend matches orders
    /// off-chain and submits settlements on-chain.
    ///
    /// In a trade:
    /// - The seller gives `amount_sold` of `asset_sold` to the buyer
    /// - The buyer gives `amount_bought` of `asset_bought` to the seller
    ///
    /// # Arguments
    /// * `buyer` - Address receiving asset_sold, paying asset_bought
    /// * `seller` - Address receiving asset_bought, paying asset_sold
    /// * `asset_sold` - The asset being sold (flows seller → buyer)
    /// * `amount_sold` - Amount of asset_sold being traded
    /// * `asset_bought` - The asset being bought (flows buyer → seller)
    /// * `amount_bought` - Amount of asset_bought being traded
    /// * `trade_id` - Unique identifier for this trade
    ///
    /// # Panics
    /// Panics if amounts are not positive, either party has insufficient balance,
    /// or admin doesn't authorize
    pub fn settle(
        env: Env,
        buyer: Address,
        seller: Address,
        asset_sold: Asset,
        amount_sold: i128,
        asset_bought: Asset,
        amount_bought: i128,
        trade_id: u64,
    ) {
        // Admin must authorize settlements
        let admin = storage::get_admin(&env);
        admin.require_auth();

        if amount_sold <= 0 || amount_bought <= 0 {
            panic!("Amounts must be positive");
        }

        storage::extend_instance_ttl(&env);

        // Update seller's balances:
        // - Decrease asset_sold (what they're selling)
        // - Increase asset_bought (what they're receiving as payment)
        storage::decrease_balance(&env, &seller, asset_sold, amount_sold);
        storage::increase_balance(&env, &seller, asset_bought, amount_bought);

        // Update buyer's balances:
        // - Increase asset_sold (what they're buying)
        // - Decrease asset_bought (what they're paying)
        storage::increase_balance(&env, &buyer, asset_sold, amount_sold);
        storage::decrease_balance(&env, &buyer, asset_bought, amount_bought);

        // Emit settle event
        events::emit_settle(
            &env,
            trade_id,
            &buyer,
            &seller,
            asset_sold,
            amount_sold,
            asset_bought,
            amount_bought,
        );
    }

    /// Get a user's balance for a specific asset.
    ///
    /// # Arguments
    /// * `user` - The user to query
    /// * `asset` - Which asset to query (A or B)
    ///
    /// # Returns
    /// The user's balance, or 0 if they have no balance
    pub fn get_balance(env: Env, user: Address, asset: Asset) -> i128 {
        storage::extend_instance_ttl(&env);
        storage::get_user_balance(&env, &user, asset)
    }

    /// Get the admin address.
    ///
    /// # Returns
    /// The admin address
    pub fn get_admin(env: Env) -> Address {
        storage::extend_instance_ttl(&env);
        storage::get_admin(&env)
    }

    /// Get the token contract address for an asset.
    ///
    /// # Arguments
    /// * `asset` - Which asset to query (A or B)
    ///
    /// # Returns
    /// The token contract address
    pub fn get_asset(env: Env, asset: Asset) -> Address {
        storage::extend_instance_ttl(&env);
        storage::get_asset_address(&env, asset)
    }
}

#[cfg(test)]
mod test;
