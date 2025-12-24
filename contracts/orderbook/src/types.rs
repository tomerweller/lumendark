use soroban_sdk::{contracttype, Address};

/// Storage keys for the contract
#[derive(Clone)]
#[contracttype]
pub enum DataKey {
    /// The admin address
    Admin,
    /// Token contract address for asset A
    AssetA,
    /// Token contract address for asset B
    AssetB,
    /// User's balance for a specific asset: UserBalance(user_address, asset)
    UserBalance(Address, Asset),
    /// Execution nonce for ensuring sequential execution order
    Nonce,
}

/// Represents which asset we're referring to
#[derive(Clone, Copy, PartialEq, Eq, Debug)]
#[contracttype]
pub enum Asset {
    A,
    B,
}
