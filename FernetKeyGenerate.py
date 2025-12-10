from cryptography.fernet import Fernet

# Generate a new Fernet key (Use only once and store it securely)

print(Fernet.generate_key().decode())