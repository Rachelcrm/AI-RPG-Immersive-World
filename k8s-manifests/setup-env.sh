#!/bin/bash

# This script helps set up the required environment variables for the AI Monitoring System

# Check if .env.example exists
if [ ! -f "../.env.example" ]; then
    echo "Error: .env.example file not found!"
    exit 1
fi

# Create a temporary file to store the environment variables
TMP_FILE=$(mktemp)

echo "Setting up environment variables for AI Monitoring System..."
echo "Please provide the following values (press Enter to use default):"

# Read the .env.example file and prompt for each variable
while IFS= read -r line || [ -n "$line" ]; do
    # Skip comments and empty lines
    if [[ $line =~ ^# ]] || [[ -z $line ]]; then
        continue
    fi

    # Extract variable name and default value
    if [[ $line =~ ^([^=]+)=(.*)$ ]]; then
        VAR_NAME="${BASH_REMATCH[1]}"
        DEFAULT_VALUE="${BASH_REMATCH[2]}"
        
        # Remove quotes from default value
        DEFAULT_VALUE="${DEFAULT_VALUE//\"/}"
        DEFAULT_VALUE="${DEFAULT_VALUE//\'/}"
        
        # Prompt for value
        read -p "$VAR_NAME [$DEFAULT_VALUE]: " VALUE
        
        # Use default if no value provided
        VALUE=${VALUE:-$DEFAULT_VALUE}
        
        # Write to temporary file
        echo "$VAR_NAME=\"$VALUE\"" >> "$TMP_FILE"
    fi
done < "../.env.example"

echo "Environment variables set up successfully!"
echo "Creating secret.yaml with the provided values..."

# Create secret.yaml with the provided values
cat > secret.yaml << EOL
apiVersion: v1
kind: Secret
metadata:
  name: ai-monitoring-secrets
type: Opaque
stringData:
EOL

# Add environment variables to secret.yaml
while IFS= read -r line || [ -n "$line" ]; do
    if [[ $line =~ ^([^=]+)=\"(.*)\"$ ]]; then
        VAR_NAME="${BASH_REMATCH[1]}"
        VALUE="${BASH_REMATCH[2]}"
        echo "  $VAR_NAME: \"$VALUE\"" >> secret.yaml
    fi
done < "$TMP_FILE"

# Clean up
rm "$TMP_FILE"

echo "secret.yaml created successfully!"
echo "You can now run ./deploy.sh to deploy the application."
