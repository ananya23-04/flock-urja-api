from app.portal_client import PortalClient

client = PortalClient.from_env()
print("meters:", len(client.export()))
print("transformers:", len(client.transformers()))
print("energy readings for J100000:", len(client.energy("J100000")))