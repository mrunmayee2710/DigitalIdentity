// SPDX-License-Identifier: MIT
pragma solidity ^0.8.19;

contract DigitalIdentity {
    struct Identity {
        bool exists;
        string name;
        string candidateId;
        string institution;
        uint256 registeredAt;
        bool verified;
    }

    address public immutable owner;
    mapping(address => Identity) private identities;

    event IdentityRegistered(address indexed wallet, string candidateId, uint256 timestamp);
    event IdentityVerified(address indexed wallet, uint256 timestamp);

    constructor() {
        owner = msg.sender;
    }

    function registerIdentity(
        address wallet,
        string calldata name,
        string calldata candidateId,
        string calldata institution
    ) external {
        require(wallet != address(0), "Invalid wallet");
        require(bytes(name).length > 0 && bytes(candidateId).length > 0, "Identity required");
        require(!identities[wallet].exists, "Identity already registered");
        identities[wallet] = Identity(true, name, candidateId, institution, block.timestamp, false);
        emit IdentityRegistered(wallet, candidateId, block.timestamp);
    }

    function getIdentity(address wallet)
        external
        view
        returns (bool exists, string memory name, string memory candidateId, string memory institution, uint256 registeredAt, bool verified)
    {
        Identity storage identity = identities[wallet];
        return (identity.exists, identity.name, identity.candidateId, identity.institution, identity.registeredAt, identity.verified);
    }

    function identityExists(address wallet) external view returns (bool) {
        return identities[wallet].exists;
    }

    function verifyIdentity(address wallet) external {
        require(msg.sender == owner, "Only contract owner");
        require(identities[wallet].exists, "Identity not registered");
        identities[wallet].verified = true;
        emit IdentityVerified(wallet, block.timestamp);
    }
}