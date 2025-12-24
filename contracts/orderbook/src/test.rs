#![cfg(test)]
extern crate std;

use soroban_sdk::{testutils::Address as _, token, Address, Env};

use crate::{types::Asset, OrderBookContract, OrderBookContractClient};

fn create_token_contract<'a>(env: &Env, admin: &Address) -> token::Client<'a> {
    token::Client::new(
        env,
        &env.register_stellar_asset_contract_v2(admin.clone())
            .address(),
    )
}

fn create_orderbook<'a>(env: &Env) -> (OrderBookContractClient<'a>, Address, Address, Address) {
    let admin = Address::generate(env);
    let token_a = create_token_contract(env, &admin);
    let token_b = create_token_contract(env, &admin);

    // Register with constructor arguments: (admin, asset_a, asset_b)
    let contract_id = env.register(
        OrderBookContract,
        (&admin, &token_a.address, &token_b.address),
    );
    let client = OrderBookContractClient::new(env, &contract_id);

    (client, admin, token_a.address, token_b.address)
}

#[test]
fn test_constructor() {
    let env = Env::default();
    env.mock_all_auths();

    let (client, admin, token_a, token_b) = create_orderbook(&env);

    assert_eq!(client.get_admin(), admin);
    assert_eq!(client.get_asset(&Asset::A), token_a);
    assert_eq!(client.get_asset(&Asset::B), token_b);
}

#[test]
fn test_deposit() {
    let env = Env::default();
    env.mock_all_auths();

    let (client, _admin, token_a_addr, _token_b_addr) = create_orderbook(&env);
    let token_a = token::Client::new(&env, &token_a_addr);

    let user = Address::generate(&env);
    let deposit_amount: i128 = 1000_0000000; // 1000 with 7 decimals

    // Mint tokens to user
    token::StellarAssetClient::new(&env, &token_a_addr).mint(&user, &deposit_amount);

    // Check initial balance
    assert_eq!(client.get_balance(&user, &Asset::A), 0);

    // Deposit
    client.deposit(&user, &Asset::A, &deposit_amount);

    // Check balance after deposit
    assert_eq!(client.get_balance(&user, &Asset::A), deposit_amount);

    // Check token was transferred to contract
    assert_eq!(token_a.balance(&user), 0);
    assert_eq!(token_a.balance(&client.address), deposit_amount);
}

#[test]
fn test_deposit_requires_user_auth() {
    let env = Env::default();
    env.mock_all_auths();

    let (client, _admin, token_a_addr, _) = create_orderbook(&env);
    let user = Address::generate(&env);
    let deposit_amount: i128 = 1000_0000000;

    token::StellarAssetClient::new(&env, &token_a_addr).mint(&user, &deposit_amount);

    client.deposit(&user, &Asset::A, &deposit_amount);

    // Verify user authorization was required
    let auths = env.auths();
    assert!(!auths.is_empty());
    // The first auth should be from the user for the deposit
    assert_eq!(auths[0].0, user);
}

#[test]
#[should_panic(expected = "Amount must be positive")]
fn test_deposit_zero_amount_fails() {
    let env = Env::default();
    env.mock_all_auths();

    let (client, _, _, _) = create_orderbook(&env);
    let user = Address::generate(&env);

    client.deposit(&user, &Asset::A, &0);
}

#[test]
fn test_withdraw() {
    let env = Env::default();
    env.mock_all_auths();

    let (client, _admin, token_a_addr, _) = create_orderbook(&env);
    let token_a = token::Client::new(&env, &token_a_addr);

    let user = Address::generate(&env);
    let amount: i128 = 1000_0000000;

    // Mint and deposit
    token::StellarAssetClient::new(&env, &token_a_addr).mint(&user, &amount);
    client.deposit(&user, &Asset::A, &amount);

    // Withdraw half (nonce starts at 0)
    let withdraw_amount = amount / 2;
    client.withdraw(&0, &user, &Asset::A, &withdraw_amount);

    // Check balances
    assert_eq!(
        client.get_balance(&user, &Asset::A),
        amount - withdraw_amount
    );
    assert_eq!(token_a.balance(&user), withdraw_amount);
}

#[test]
fn test_withdraw_requires_admin_auth() {
    let env = Env::default();
    env.mock_all_auths();

    let (client, admin, token_a_addr, _) = create_orderbook(&env);
    let user = Address::generate(&env);
    let amount: i128 = 1000_0000000;

    token::StellarAssetClient::new(&env, &token_a_addr).mint(&user, &amount);
    client.deposit(&user, &Asset::A, &amount);

    // Clear previous auths
    let _ = env.auths();

    client.withdraw(&0, &user, &Asset::A, &amount);

    // Verify admin authorization was required (first auth in the list)
    let auths = env.auths();
    assert!(!auths.is_empty());
    assert_eq!(auths[0].0, admin);
}

#[test]
#[should_panic(expected = "Insufficient balance")]
fn test_withdraw_insufficient_balance_fails() {
    let env = Env::default();
    env.mock_all_auths();

    let (client, _, token_a_addr, _) = create_orderbook(&env);
    let user = Address::generate(&env);
    let amount: i128 = 1000_0000000;

    token::StellarAssetClient::new(&env, &token_a_addr).mint(&user, &amount);
    client.deposit(&user, &Asset::A, &amount);

    // Try to withdraw more than deposited
    client.withdraw(&0, &user, &Asset::A, &(amount + 1));
}

#[test]
fn test_settle() {
    let env = Env::default();
    env.mock_all_auths();

    let (client, _admin, token_a_addr, token_b_addr) = create_orderbook(&env);

    let buyer = Address::generate(&env);
    let seller = Address::generate(&env);

    // Initial setup:
    // - Buyer has 1000 B (to pay for A)
    // - Seller has 100 A (to sell)
    let buyer_b_amount: i128 = 1000_0000000;
    let seller_a_amount: i128 = 100_0000000;

    token::StellarAssetClient::new(&env, &token_b_addr).mint(&buyer, &buyer_b_amount);
    token::StellarAssetClient::new(&env, &token_a_addr).mint(&seller, &seller_a_amount);

    client.deposit(&buyer, &Asset::B, &buyer_b_amount);
    client.deposit(&seller, &Asset::A, &seller_a_amount);

    // Trade: Seller sells 50 A to Buyer for 500 B (nonce=0)
    let trade_a_amount: i128 = 50_0000000;
    let trade_b_amount: i128 = 500_0000000;

    client.settle(
        &0,              // nonce
        &buyer,
        &seller,
        &Asset::A,       // asset_sold (A flows seller → buyer)
        &trade_a_amount, // amount_sold
        &Asset::B,       // asset_bought (B flows buyer → seller)
        &trade_b_amount, // amount_bought
    );

    // Check buyer balances:
    // - Should have 50 A (received from seller)
    // - Should have 500 B (1000 - 500 paid to seller)
    assert_eq!(client.get_balance(&buyer, &Asset::A), trade_a_amount);
    assert_eq!(
        client.get_balance(&buyer, &Asset::B),
        buyer_b_amount - trade_b_amount
    );

    // Check seller balances:
    // - Should have 50 A (100 - 50 sold to buyer)
    // - Should have 500 B (received from buyer)
    assert_eq!(
        client.get_balance(&seller, &Asset::A),
        seller_a_amount - trade_a_amount
    );
    assert_eq!(client.get_balance(&seller, &Asset::B), trade_b_amount);
}

#[test]
fn test_settle_requires_admin_auth() {
    let env = Env::default();
    env.mock_all_auths();

    let (client, admin, token_a_addr, token_b_addr) = create_orderbook(&env);

    let buyer = Address::generate(&env);
    let seller = Address::generate(&env);

    let buyer_b_amount: i128 = 1000_0000000;
    let seller_a_amount: i128 = 100_0000000;

    token::StellarAssetClient::new(&env, &token_b_addr).mint(&buyer, &buyer_b_amount);
    token::StellarAssetClient::new(&env, &token_a_addr).mint(&seller, &seller_a_amount);

    client.deposit(&buyer, &Asset::B, &buyer_b_amount);
    client.deposit(&seller, &Asset::A, &seller_a_amount);

    // Clear previous auths
    let _ = env.auths();

    client.settle(&0, &buyer, &seller, &Asset::A, &50_0000000, &Asset::B, &500_0000000);

    // Verify admin authorization was required
    let auths = env.auths();
    assert!(!auths.is_empty());
    assert_eq!(auths[0].0, admin);
}

#[test]
#[should_panic(expected = "Insufficient balance")]
fn test_settle_seller_insufficient_balance_fails() {
    let env = Env::default();
    env.mock_all_auths();

    let (client, _, token_a_addr, token_b_addr) = create_orderbook(&env);

    let buyer = Address::generate(&env);
    let seller = Address::generate(&env);

    let buyer_b_amount: i128 = 1000_0000000;
    let seller_a_amount: i128 = 100_0000000;

    token::StellarAssetClient::new(&env, &token_b_addr).mint(&buyer, &buyer_b_amount);
    token::StellarAssetClient::new(&env, &token_a_addr).mint(&seller, &seller_a_amount);

    client.deposit(&buyer, &Asset::B, &buyer_b_amount);
    client.deposit(&seller, &Asset::A, &seller_a_amount);

    // Try to settle more A than seller has
    client.settle(
        &0,  // nonce
        &buyer,
        &seller,
        &Asset::A,
        &(seller_a_amount + 1), // More than seller has
        &Asset::B,
        &500_0000000,
    );
}

#[test]
#[should_panic(expected = "Insufficient balance")]
fn test_settle_buyer_insufficient_balance_fails() {
    let env = Env::default();
    env.mock_all_auths();

    let (client, _, token_a_addr, token_b_addr) = create_orderbook(&env);

    let buyer = Address::generate(&env);
    let seller = Address::generate(&env);

    let buyer_b_amount: i128 = 1000_0000000;
    let seller_a_amount: i128 = 100_0000000;

    token::StellarAssetClient::new(&env, &token_b_addr).mint(&buyer, &buyer_b_amount);
    token::StellarAssetClient::new(&env, &token_a_addr).mint(&seller, &seller_a_amount);

    client.deposit(&buyer, &Asset::B, &buyer_b_amount);
    client.deposit(&seller, &Asset::A, &seller_a_amount);

    // Try to settle more B than buyer has
    client.settle(
        &0,  // nonce
        &buyer,
        &seller,
        &Asset::A,
        &50_0000000,
        &Asset::B,
        &(buyer_b_amount + 1), // More than buyer has
    );
}

#[test]
fn test_multiple_deposits_same_user() {
    let env = Env::default();
    env.mock_all_auths();

    let (client, _, token_a_addr, _) = create_orderbook(&env);

    let user = Address::generate(&env);
    let amount1: i128 = 1000_0000000;
    let amount2: i128 = 500_0000000;

    token::StellarAssetClient::new(&env, &token_a_addr).mint(&user, &(amount1 + amount2));

    client.deposit(&user, &Asset::A, &amount1);
    client.deposit(&user, &Asset::A, &amount2);

    assert_eq!(client.get_balance(&user, &Asset::A), amount1 + amount2);
}

#[test]
fn test_multiple_users() {
    let env = Env::default();
    env.mock_all_auths();

    let (client, _, token_a_addr, token_b_addr) = create_orderbook(&env);

    let user1 = Address::generate(&env);
    let user2 = Address::generate(&env);

    let user1_a: i128 = 1000_0000000;
    let user2_b: i128 = 500_0000000;

    token::StellarAssetClient::new(&env, &token_a_addr).mint(&user1, &user1_a);
    token::StellarAssetClient::new(&env, &token_b_addr).mint(&user2, &user2_b);

    client.deposit(&user1, &Asset::A, &user1_a);
    client.deposit(&user2, &Asset::B, &user2_b);

    assert_eq!(client.get_balance(&user1, &Asset::A), user1_a);
    assert_eq!(client.get_balance(&user1, &Asset::B), 0);
    assert_eq!(client.get_balance(&user2, &Asset::A), 0);
    assert_eq!(client.get_balance(&user2, &Asset::B), user2_b);
}

#[test]
fn test_full_flow_deposit_trade_withdraw() {
    let env = Env::default();
    env.mock_all_auths();

    let (client, _, token_a_addr, token_b_addr) = create_orderbook(&env);
    let token_a = token::Client::new(&env, &token_a_addr);
    let token_b = token::Client::new(&env, &token_b_addr);

    let alice = Address::generate(&env); // Seller of A
    let bob = Address::generate(&env); // Buyer of A

    // Initial: Alice has 100 A, Bob has 1000 B
    let alice_a: i128 = 100_0000000;
    let bob_b: i128 = 1000_0000000;

    token::StellarAssetClient::new(&env, &token_a_addr).mint(&alice, &alice_a);
    token::StellarAssetClient::new(&env, &token_b_addr).mint(&bob, &bob_b);

    // 1. Deposits
    client.deposit(&alice, &Asset::A, &alice_a);
    client.deposit(&bob, &Asset::B, &bob_b);

    // Check initial nonce is 0
    assert_eq!(client.get_nonce(), 0);

    // 2. Trade: Alice sells 50 A to Bob for 500 B (nonce=0, increments to 1)
    let trade_a: i128 = 50_0000000;
    let trade_b: i128 = 500_0000000;
    client.settle(&0, &bob, &alice, &Asset::A, &trade_a, &Asset::B, &trade_b);
    assert_eq!(client.get_nonce(), 1);

    // 3. Withdrawals (nonces: 1, 2, 3, 4)
    // Alice withdraws her remaining 50 A and her 500 B profit
    client.withdraw(&1, &alice, &Asset::A, &(alice_a - trade_a));
    assert_eq!(client.get_nonce(), 2);
    client.withdraw(&2, &alice, &Asset::B, &trade_b);
    assert_eq!(client.get_nonce(), 3);

    // Bob withdraws his 50 A and remaining 500 B
    client.withdraw(&3, &bob, &Asset::A, &trade_a);
    assert_eq!(client.get_nonce(), 4);
    client.withdraw(&4, &bob, &Asset::B, &(bob_b - trade_b));
    assert_eq!(client.get_nonce(), 5);

    // 4. Verify final token balances
    assert_eq!(token_a.balance(&alice), alice_a - trade_a); // 50 A
    assert_eq!(token_b.balance(&alice), trade_b); // 500 B

    assert_eq!(token_a.balance(&bob), trade_a); // 50 A
    assert_eq!(token_b.balance(&bob), bob_b - trade_b); // 500 B

    // 5. Verify contract balances are zero
    assert_eq!(client.get_balance(&alice, &Asset::A), 0);
    assert_eq!(client.get_balance(&alice, &Asset::B), 0);
    assert_eq!(client.get_balance(&bob, &Asset::A), 0);
    assert_eq!(client.get_balance(&bob, &Asset::B), 0);
}

#[test]
#[should_panic(expected = "Invalid nonce")]
fn test_settle_invalid_nonce_fails() {
    let env = Env::default();
    env.mock_all_auths();

    let (client, _, token_a_addr, token_b_addr) = create_orderbook(&env);

    let buyer = Address::generate(&env);
    let seller = Address::generate(&env);

    let buyer_b_amount: i128 = 1000_0000000;
    let seller_a_amount: i128 = 100_0000000;

    token::StellarAssetClient::new(&env, &token_b_addr).mint(&buyer, &buyer_b_amount);
    token::StellarAssetClient::new(&env, &token_a_addr).mint(&seller, &seller_a_amount);

    client.deposit(&buyer, &Asset::B, &buyer_b_amount);
    client.deposit(&seller, &Asset::A, &seller_a_amount);

    // Try to settle with wrong nonce (expected 0, providing 1)
    client.settle(&1, &buyer, &seller, &Asset::A, &50_0000000, &Asset::B, &500_0000000);
}

#[test]
#[should_panic(expected = "Invalid nonce")]
fn test_withdraw_invalid_nonce_fails() {
    let env = Env::default();
    env.mock_all_auths();

    let (client, _, token_a_addr, _) = create_orderbook(&env);
    let user = Address::generate(&env);
    let amount: i128 = 1000_0000000;

    token::StellarAssetClient::new(&env, &token_a_addr).mint(&user, &amount);
    client.deposit(&user, &Asset::A, &amount);

    // Try to withdraw with wrong nonce (expected 0, providing 5)
    client.withdraw(&5, &user, &Asset::A, &amount);
}
