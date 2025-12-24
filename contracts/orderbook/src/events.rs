use soroban_sdk::{symbol_short, Address, Env};

use crate::types::Asset;

/// Emit a deposit event
/// Topics: ("deposit", user)
/// Data: (asset, amount)
pub fn emit_deposit(env: &Env, user: &Address, asset: Asset, amount: i128) {
    let topics = (symbol_short!("deposit"), user.clone());
    let data = (asset, amount);
    env.events().publish(topics, data);
}

/// Emit a withdraw event
/// Topics: ("withdraw", nonce)
/// Data: (user, asset, amount)
pub fn emit_withdraw(env: &Env, nonce: u64, user: &Address, asset: Asset, amount: i128) {
    let topics = (symbol_short!("withdraw"), nonce);
    let data = (user.clone(), asset, amount);
    env.events().publish(topics, data);
}

/// Emit a settle event for a trade
/// Topics: ("settle", nonce)
/// Data: (buyer, seller, asset_sold, amount_sold, asset_bought, amount_bought)
pub fn emit_settle(
    env: &Env,
    nonce: u64,
    buyer: &Address,
    seller: &Address,
    asset_sold: Asset,
    amount_sold: i128,
    asset_bought: Asset,
    amount_bought: i128,
) {
    let topics = (symbol_short!("settle"), nonce);
    let data = (
        buyer.clone(),
        seller.clone(),
        asset_sold,
        amount_sold,
        asset_bought,
        amount_bought,
    );
    env.events().publish(topics, data);
}
