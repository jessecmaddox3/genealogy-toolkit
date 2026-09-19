"""Normal tests must not contact archives, accounts, or any network service."""
import socket
import pytest


@pytest.fixture(autouse=True)
def deny_network(monkeypatch):
    def denied(*args,**kwargs):raise AssertionError('Network access is disabled in the test suite')
    monkeypatch.setattr(socket.socket,'connect',denied)
    monkeypatch.setattr(socket,'create_connection',denied)
