use soroban_sdk::{Address, Env};

use crate::types::{Asset, DataKey};

// TTL constants for storage entries
const DAY_IN_LEDGERS: u32 = 17280; // ~24 hours at 5s per ledger
const INSTANCE_BUMP_AMOUNT: u32 = 7 * DAY_IN_LEDGERS;
const INSTANCE_LIFETIME_THRESHOLD: u32 = DAY_IN_LEDGERS;
const BALANCE_BUMP_AMOUNT: u32 = 30 * DAY_IN_LEDGERS;
const BALANCE_LIFETIME_THRESHOLD: u32 = 7 * DAY_IN_LEDGERS;

/// Extend the TTL of instance storage
pub fn extend_instance_ttl(env: &Env) {
    env.storage()
        .instance()
        .extend_ttl(INSTANCE_LIFETIME_THRESHOLD, INSTANCE_BUMP_AMOUNT);
}

/// Get the admin address
pub fn get_admin(env: &Env) -> Address {
    env.storage()
        .instance()
        .get(&DataKey::Admin)
        .expect("Admin not set")
}

/// Set the admin address
pub fn set_admin(env: &Env, admin: &Address) {
    env.storage().instance().set(&DataKey::Admin, admin);
}

/// Get the token contract address for an asset
pub fn get_asset_address(env: &Env, asset: Asset) -> Address {
    let key = match asset {
        Asset::A => DataKey::AssetA,
        Asset::B => DataKey::AssetB,
    };
    env.storage()
        .instance()
        .get(&key)
        .expect("Asset not set")
}

/// Set the token contract address for asset A
pub fn set_asset_a(env: &Env, address: &Address) {
    env.storage().instance().set(&DataKey::AssetA, address);
}

/// Set the token contract address for asset B
pub fn set_asset_b(env: &Env, address: &Address) {
    env.storage().instance().set(&DataKey::AssetB, address);
}

/// Get a user's balance for a specific asset
/// Returns 0 if the user has no balance entry
pub fn get_user_balance(env: &Env, user: &Address, asset: Asset) -> i128 {
    let key = DataKey::UserBalance(user.clone(), asset);
    env.storage().persistent().get(&key).unwrap_or(0)
}

/// Set a user's balance for a specific asset
pub fn set_user_balance(env: &Env, user: &Address, asset: Asset, balance: i128) {
    let key = DataKey::UserBalance(user.clone(), asset);
    env.storage().persistent().set(&key, &balance);

    // Extend TTL for the balance entry
    env.storage().persistent().extend_ttl(
        &key,
        BALANCE_LIFETIME_THRESHOLD,
        BALANCE_BUMP_AMOUNT,
    );
}

/// Increase a user's balance for a specific asset
pub fn increase_balance(env: &Env, user: &Address, asset: Asset, amount: i128) {
    let current = get_user_balance(env, user, asset);
    set_user_balance(env, user, asset, current + amount);
}

/// Decrease a user's balance for a specific asset
/// Panics if the user doesn't have enough balance
pub fn decrease_balance(env: &Env, user: &Address, asset: Asset, amount: i128) {
    let current = get_user_balance(env, user, asset);
    if current < amount {
        panic!("Insufficient balance");
    }
    set_user_balance(env, user, asset, current - amount);
}

/// Get the current nonce value
/// Returns 0 if not yet initialized
pub fn get_nonce(env: &Env) -> u64 {
    env.storage()
        .instance()
        .get(&DataKey::Nonce)
        .unwrap_or(0)
}

/// Validate that the provided nonce matches the current nonce
/// Panics if the nonce doesn't match
pub fn validate_nonce(env: &Env, expected_nonce: u64) {
    let current = get_nonce(env);
    if expected_nonce != current {
        panic!("Invalid nonce: expected {}, got {}", current, expected_nonce);
    }
}

/// Increment the nonce by 1
pub fn increment_nonce(env: &Env) {
    let current = get_nonce(env);
    env.storage()
        .instance()
        .set(&DataKey::Nonce, &(current + 1));
}
