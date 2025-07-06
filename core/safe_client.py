

import os
import requests
from dotenv import load_dotenv
from eth_account import Account
from eth_account.messages import encode_typed_data
from web3 import Web3
import config

load_dotenv()

class SafeClient:
    """
    Manages Gnosis Safe multisig transactions via the Safe Transaction Service API.
    Proposes deposit transactions for configured Safe wallets using a single service account key.
    Only handles sending funds into the multisig; does not support withdrawal or execution flows.
    """
    def __init__(
        self,
        rpc_url: str = None,
        service_url: str = None,
        chain_id: int = None
    ):
        # Load configuration
        self.service_url = service_url or config.SAFE_SERVICE_URL
        self.rpc_url      = rpc_url      or config.ETHEREUM_RPC_URL
        self.chain_id     = chain_id     or config.CHAIN_ID

        # Initialize Web3
        self.w3 = Web3(Web3.HTTPProvider(self.rpc_url))

        # Service account used to propose transactions
        self.service_key     = config.SERVICE_ACCOUNT_PRIVATE_KEY
        self.service_address = Account.from_key(self.service_key).address

        # Prepare multisig clients
        self._clients: dict[str, dict] = {}

        # Primary multisig (2-of-2)
        primary_addr = Web3.to_checksum_address(config.MULTISIG_GHOST_WALLET_2OF2)
        self._clients['primary'] = {
            'safe_address': primary_addr,
            'threshold':    2
        }

        # Admin pool multisig (5-of-5)
        pool_addr = Web3.to_checksum_address(config.SECOND_ADMIN_POOL_WALLET)
        self._clients['admin_pool'] = {
            'safe_address': pool_addr,
            'threshold':    5
        }

        # # Personal admin multisigs (each 2-of-2)
        # for idx, raw_addr in enumerate(config.SECOND_ADMIN_PERSONAL_WALLETS, start=1):
        #     alias = f'admin_personal_{idx}'
        #     addr  = Web3.to_checksum_address(raw_addr.strip())
        #     self._clients[alias] = {
        #         'safe_address': addr,
        #         'threshold':    2
        #     }

    def _get_client(self, alias: str) -> dict:
        """Retrieve the client config for the given alias."""
        if alias not in self._clients:
            raise ValueError(f"Unknown safe alias '{alias}'")
        return self._clients[alias]

    def get_safe_nonce(self, alias: str = 'primary') -> int:
        """Fetch the current nonce for the specified Safe wallet."""
        client = self._get_client(alias)
        url = f"{self.service_url}/api/v1/safes/{client['safe_address']}/"
        resp = requests.get(url)
        resp.raise_for_status()
        return resp.json()['nonce']

    def build_safe_tx(
        self,
        to: str,
        value_wei: int,
        data: str,
        alias: str
    ) -> dict:
        """Construct the Safe transaction payload for the given wallet alias."""
        client = self._get_client(alias)
        return {
            'to':             Web3.to_checksum_address(to),
            'value':          str(value_wei),
            'data':           data,
            'operation':      0,
            'safeTxGas':      0,
            'baseGas':        0,
            'gasPrice':       '0',
            'gasToken':       '0x0000000000000000000000000000000000000000',
            'refundReceiver': '0x0000000000000000000000000000000000000000',
            'nonce':          self.get_safe_nonce(alias)
        }

    def sign_safe_txn(
        self,
        safe_tx: dict,
        private_key: str,
        safe_address: str
    ) -> str:
        """Sign the Safe transaction payload using EIP-712."""
        domain = {
            'chainId':           self.chain_id,
            'verifyingContract': safe_address
        }
        types = {
            'EIP712Domain': [
                {'name': 'chainId',           'type': 'uint256'},
                {'name': 'verifyingContract', 'type': 'address'}
            ],
            'SafeTx': [
                {'name': 'to',             'type': 'address'},
                {'name': 'value',          'type': 'uint256'},
                {'name': 'data',           'type': 'bytes'},
                {'name': 'operation',      'type': 'uint8'},
                {'name': 'safeTxGas',      'type': 'uint256'},
                {'name': 'baseGas',        'type': 'uint256'},
                {'name': 'gasPrice',       'type': 'uint256'},
                {'name': 'gasToken',       'type': 'address'},
                {'name': 'refundReceiver', 'type': 'address'},
                {'name': 'nonce',          'type': 'uint256'}
            ]
        }
        message = {
            'domain':      domain,
            'primaryType': 'SafeTx',
            'types':       types,
            'message':     safe_tx
        }
        encoded = encode_typed_data(message)
        acct = Account.from_key(private_key)
        signed = acct.sign_message(encoded)
        return signed.signature.hex()

    def propose(
        self,
        to: str,
        value_eth: float,
        data: str = '0x',
        alias: str = 'primary'
    ) -> dict:
        """
        Propose a new deposit transaction to the specified Safe wallet alias.
        Only handles sending funds into the multisig; does not support withdrawal.
        """
        client = self._get_client(alias)
        value_wei = self.w3.to_wei(value_eth, 'ether')
        safe_tx = self.build_safe_tx(to, value_wei, data, alias)
        signature = self.sign_safe_txn(
            safe_tx,
            self.service_key,
            client['safe_address']
        )
        payload = {
            **safe_tx,
            'sender':    self.service_address,
            'signature': signature
        }
        url = (
            f"{self.service_url}/api/v1/safes/"
            f"{client['safe_address']}/multisig-transactions/"
        )
        resp = requests.post(url, json=payload)
        resp.raise_for_status()
        return resp.json()



# # safe_client.py

# import os
# import requests
# from dotenv import load_dotenv
# from eth_account import Account
# from eth_account.messages import encode_typed_data
# from web3 import Web3
# import config

# load_dotenv()

# class SafeClient:
#     """
#     Manages multiple Gnosis Safe (2-of-2) wallets via the Safe Transaction Service API.
#     Supports both primary and multiple secondary (admin pool) multisig wallets using a single class.
#     """
#     def __init__(
#         self,
#         rpc_url: str = None,
#         service_url: str = None,
#         chain_id: int = None
#     ):
#         # Load configuration
#         self.service_url = service_url or config.SAFE_SERVICE_URL
#         self.rpc_url      = rpc_url      or config.ETHEREUM_RPC_URL
#         self.chain_id     = chain_id     or config.CHAIN_ID

#         # Initialize Web3 for utility functions (e.g., to_wei)
#         self.w3 = Web3(Web3.HTTPProvider(self.rpc_url))

#         # Prepare client definitions for each multisig wallet
#         self._clients: dict[str, dict] = {}

#         # Primary multisig
#         primary_addr = Web3.to_checksum_address(config.MULTISIG_GHOST_WALLET_2OF2)
#         self._clients['primary'] = {
#             'safe_address': primary_addr,
#             'owner1_key':   config.OWNER1_GHOST_PRIVATE_KEY,
#             'owner2_key':   config.OWNER2_GHOST_PRIVATE_KEY
#         }
        
#         #---------------------------------------------------------------------------------------
#         # Admin pool multisig (5-member multisig)
#         pool = Web3.to_checksum_address(config.SECOND_ADMIN_POOL_WALLET)
        
#         # استخراج کلیدهای خصوصی از متغیر محیطی
#         admin_private_keys = []
#         if hasattr(config, 'SECOND_ADMIN_PRIVATE_KEYS'):
#             # اگر یک متغیر جداگانه برای private key ها داری
#             admin_private_keys = config.SECOND_ADMIN_PRIVATE_KEYS
#         else:
#             # اگر نداری، باید آدرس‌ها رو به private key تبدیل کنی
#             # یا از یک نقشه (mapping) استفاده کنی
#             raise ValueError("SECOND_ADMIN_PRIVATE_KEYS not found in config")
        
#         self._clients['admin_pool'] = {
#             'safe_address': pool,
#             'owners': admin_private_keys,
#             'threshold': getattr(config, 'ADMIN_POOL_THRESHOLD', 3)  # پیش‌فرض 3 از 5
#         }

#         # Personal admin multisigs (هر کدام 2-of-2)
#         admin_addresses = config.SECOND_ADMIN_PERSONAL_WALLETS
#         for idx, raw_addr in enumerate(admin_addresses, start=1):
#             alias = f'admin_personal_{idx}'
#             addr  = Web3.to_checksum_address(raw_addr.strip())
#             self._clients[alias] = {
#                 'safe_address': addr,
#                 'owner1_key':   admin_private_keys[idx-1],  # کلید مربوط به همان عضو
#                 'owner2_key':   config.OWNER2_GHOST_PRIVATE_KEY   # یا هر کلید دوم مناسب
#             }
#     #-----------------------------------------------------------------------------------------
#     def _get_client(self, alias: str) -> dict:
#         if alias not in self._clients:
#             raise ValueError(f"Unknown safe alias '{alias}'")
#         return self._clients[alias]
    
#     #-----------------------------------------------------------------------------------------
#     def get_safe_nonce(self, alias: str = 'primary') -> int:
#         """Fetch the current nonce for the specified Safe wallet."""
#         client = self._get_client(alias)
#         url = f"{self.service_url}/api/v1/safes/{client['safe_address']}/"
#         resp = requests.get(url)
#         resp.raise_for_status()
#         return resp.json()['nonce']
    
#     #-----------------------------------------------------------------------------------------
#     def build_safe_tx(
#         self,
#         to: str,
#         value_wei: int,
#         data: str = "0x",
#         alias: str = 'primary'
#     ) -> dict:
#         """Construct the Safe transaction payload for the given wallet alias."""
#         client = self._get_client(alias)
#         return {
#             'to':             Web3.to_checksum_address(to),
#             'value':          str(value_wei),
#             'data':           data,
#             'operation':      0,
#             'safeTxGas':      0,
#             'baseGas':        0,
#             'gasPrice':       '0',
#             'gasToken':       '0x0000000000000000000000000000000000000000',
#             'refundReceiver': '0x0000000000000000000000000000000000000000',
#             'nonce':          self.get_safe_nonce(alias),
#         }
        
#     #-----------------------------------------------------------------------------------------
#     def sign_safe_txn(
#         self,
#         safe_tx: dict,
#         private_key: str,
#         safe_address: str
#     ) -> str:
#         """Sign the Safe transaction payload using EIP-712."""
#         domain = {
#             'chainId':           self.chain_id,
#             'verifyingContract': safe_address
#         }
#         types = {
#             'EIP712Domain': [
#                 {'name': 'chainId',           'type': 'uint256'},
#                 {'name': 'verifyingContract', 'type': 'address'}
#             ],
#             'SafeTx': [
#                 {'name': 'to',             'type': 'address'},
#                 {'name': 'value',          'type': 'uint256'},
#                 {'name': 'data',           'type': 'bytes'},
#                 {'name': 'operation',      'type': 'uint8'},
#                 {'name': 'safeTxGas',      'type': 'uint256'},
#                 {'name': 'baseGas',        'type': 'uint256'},
#                 {'name': 'gasPrice',       'type': 'uint256'},
#                 {'name': 'gasToken',       'type': 'address'},
#                 {'name': 'refundReceiver', 'type': 'address'},
#                 {'name': 'nonce',          'type': 'uint256'},
#             ]
#         }
#         message = {
#             'domain':      domain,
#             'primaryType': 'SafeTx',
#             'types':       types,
#             'message':     safe_tx
#         }
#         encoded = encode_typed_data(message)
#         acct = Account.from_key(private_key)
#         signed = acct.sign_message(encoded)
#         return signed.signature.hex()
    
#     #-----------------------------------------------------------------------------------------
#     def propose(
#         self,
#         to: str,
#         value_eth: float,
#         data: str = "0x",
#         alias: str = 'primary'
#     ) -> dict:
#         """Propose a new Safe transaction from the specified wallet alias."""
#         client = self._get_client(alias)
#         value_wei = self.w3.to_wei(value_eth, 'ether')
#         safe_tx = self.build_safe_tx(to, value_wei, data, alias)
#         sig = self.sign_safe_txn(
#             safe_tx,
#             client['owner1_key'],
#             client['safe_address']
#         )
#         payload = {
#             **safe_tx,
#             'sender':    Account.from_key(client['owner1_key']).address,
#             'signature': sig
#         }
#         url = (
#             f"{self.service_url}/api/v1/safes/"
#             f"{client['safe_address']}/multisig-transactions/"
#         )
#         resp = requests.post(url, json=payload)
#         resp.raise_for_status()
#         return resp.json()

#     def confirm(
#         self,
#         safe_tx_hash: str,
#         alias: str = 'primary'
#     ) -> dict:
#         """Confirm a proposed Safe transaction from the specified wallet alias."""
#         client = self._get_client(alias)
#         sig = self.sign_safe_txn(
#             {
#                 'to': '', 'value': 0, 'data': '0x', 'operation': 0,
#                 'safeTxGas': 0, 'baseGas': 0, 'gasPrice': 0,
#                 'gasToken':           client['safe_address'],
#                 'refundReceiver':     client['safe_address'],
#                 'nonce':              0
#             },
#             client['owner2_key'],
#             client['safe_address']
#         )
#         payload = {
#             'signature': sig,
#             'owner':     Account.from_key(client['owner2_key']).address
#         }
#         url = (
#             f"{self.service_url}/api/v1/multisig-transactions/"
#             f"{safe_tx_hash}/confirmations/"
#         )
#         resp = requests.post(url, json=payload)
#         resp.raise_for_status()
#         return resp.json()

#     def execute(
#         self,
#         safe_tx_hash: str,
#         alias: str = 'primary'
#     ) -> dict:
#         """Execute a confirmed Safe transaction from the specified wallet alias."""
#         client = self._get_client(alias)
#         url = (
#             f"{self.service_url}/api/v1/safes/"
#             f"{client['safe_address']}/multisig-transactions/"
#             f"{safe_tx_hash}/execute/"
#         )
#         resp = requests.post(url)
#         resp.raise_for_status()
#         return resp.json()



