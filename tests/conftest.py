

def pytest_configure(config):
    config.addinivalue_line("markers", "integration: real LLM calls (slow, costs money)")
