# Pet Order REST API - Assignment 2
from flask import Flask, jsonify, request
import requests
import os
import random
from pymongo import MongoClient, ReturnDocument

app = Flask(__name__)

# MongoDB Connection
MONGO_URI = os.getenv('MONGO_URI', 'mongodb://mongodb:27017/')
db_client = MongoClient(MONGO_URI)
db = db_client['pet_store']
transactions_collection = db['transactions']

# Counter for purchase IDs
counters_collection = db['counters']

# Pet-store service URLs
PET_STORE_URLS = {
    1: "http://pet-store1:8000",
    2: "http://pet-store2:8000"
}

# Owner password
OWNER_PASSWORD = "LovesPetsL2M3n4"

def get_next_purchase_id():
    """Get next purchase ID using MongoDB counter"""
    result = counters_collection.find_one_and_update(
        {"_id": "purchase_id"},
        {"$inc": {"seq": 1}},
        upsert=True,
        return_document=ReturnDocument.AFTER
    )
    return str(result['seq'])

def find_pet_type_id(pet_type_name):
    """Find pet-type ID by name from pet-stores"""
    # Try both stores
    for store in [1, 2]:
        try:
            url = f"{PET_STORE_URLS[store]}/pet-types"
            response = requests.get(url, timeout=5)

            if response.status_code == 200:
                pet_types = response.json()

                # Search for matching pet-type (case-insensitive)
                for pet_type in pet_types:
                    if pet_type['type'].lower() == pet_type_name.lower():
                        return pet_type['id']
        except Exception as e:
            print(f"Error querying store {store}: {e}")
            continue

    return None

def select_pet(pet_type_id, store=None, pet_name=None):
    """Select a pet based on request parameters"""

    # Case 1: Store AND pet-name specified - get specific pet
    if store and pet_name:
        try:
            url = f"{PET_STORE_URLS[store]}/pet-types/{pet_type_id}/pets/{pet_name}"
            response = requests.get(url, timeout=5)

            if response.status_code == 200:
                return response.json(), store
        except Exception as e:
            print(f"Error getting specific pet: {e}")

        return None, None

    # Case 2: Only store specified - random pet from that store
    if store:
        try:
            url = f"{PET_STORE_URLS[store]}/pet-types/{pet_type_id}/pets"
            response = requests.get(url, timeout=5)

            if response.status_code == 200:
                pets = response.json()
                if pets:
                    return random.choice(pets), store
        except Exception as e:
            print(f"Error getting pets from store {store}: {e}")

        return None, None

    # Case 3: No store specified - try both stores, pick random
    for try_store in [1, 2]:
        try:
            url = f"{PET_STORE_URLS[try_store]}/pet-types/{pet_type_id}/pets"
            response = requests.get(url, timeout=5)

            if response.status_code == 200:
                pets = response.json()
                if pets:
                    return random.choice(pets), try_store
        except Exception as e:
            print(f"Error getting pets from store {try_store}: {e}")
            continue

    return None, None

@app.route('/purchases', methods=['POST'])
def create_purchase():
    """Handle pet purchase requests"""
    print(f"POST /purchases")
    try:
        # Validate Content-Type
        content_type = request.headers.get('Content-Type')
        if content_type != 'application/json':
            return jsonify({"error": "Expected application/json media type"}), 415

        data = request.get_json()

        # Required fields
        if 'purchaser' not in data or 'pet-type' not in data:
            return jsonify({"error": "Malformed data"}), 400

        purchaser = data['purchaser']
        pet_type_name = data['pet-type']
        store = data.get('store', None)  # Optional
        pet_name = data.get('pet-name', None)  # Optional

        # Find pet-type ID from pet-store
        pet_type_id = find_pet_type_id(pet_type_name)
        if not pet_type_id:
            return jsonify({"error": "No pet of this type is available"}), 400

        # Select and get pet based on request
        selected_pet, selected_store = select_pet(pet_type_id, store, pet_name)
        if not selected_pet:
            return jsonify({"error": "No pet of this type is available"}), 400

        selected_pet_name = selected_pet['name']

        # Delete pet from pet-store
        delete_url = f"{PET_STORE_URLS[selected_store]}/pet-types/{pet_type_id}/pets/{selected_pet_name}"
        delete_response = requests.delete(delete_url)

        if delete_response.status_code != 204:
            return jsonify({"error": "Failed to complete purchase"}), 400

        # Generate purchase ID
        purchase_id = get_next_purchase_id()

        # Create transaction record (store ALL fields including pet-name)
        transaction = {
            "purchaser": purchaser,
            "pet-type": pet_type_name,
            "store": selected_store,
            "pet-name": selected_pet_name,
            "purchase-id": purchase_id
        }

        # Store in MongoDB
        transactions_collection.insert_one(transaction)

        # Remove MongoDB _id before returning
        transaction.pop('_id', None)

        print(f"Purchase completed: {transaction}")
        return jsonify(transaction), 201

    except Exception as e:
        print(f"Exception in create_purchase: {str(e)}")
        return jsonify({"server error": str(e)}), 500

@app.route('/transactions', methods=['GET'])
def get_transactions():
    """Get all transactions (owner only)"""
    print(f"GET /transactions")
    try:
        # Check OwnerPC header
        owner_pc = request.headers.get('OwnerPC')
        if owner_pc != OWNER_PASSWORD:
            return jsonify({"error": "Unauthorized"}), 401

        # Build query from ALL query string parameters dynamically
        query = {}

        # Iterate through all query parameters
        for field, value in request.args.items():
            # Convert 'store' to integer
            if field == 'store':
                query[field] = int(value)
            # Case-insensitive match for string fields
            elif field in ['purchaser', 'pet-type', 'purchase-id']:
                query[field] = {"$regex": f"^{value}$", "$options": "i"}
            else:
                # For any other field, use exact match
                query[field] = value

        # Query MongoDB
        transactions = list(transactions_collection.find(query, {'_id': 0}))

        # Remove pet-name from response (but keep in database)
        for transaction in transactions:
            transaction.pop('pet-name', None)

        print(f"Retrieved {len(transactions)} transactions with query: {query}")
        return jsonify(transactions), 200

    except Exception as e:
        print(f"Exception in get_transactions: {str(e)}")
        return jsonify({"server error": str(e)}), 500

@app.route('/kill', methods=['GET'])
def kill_container():
    """Kill container for testing Docker Compose restart"""
    print("KILL endpoint called - terminating container")
    os._exit(1)

if __name__ == '__main__':
    print("Starting Pet Order API server...")
    print(f"Pet Store URLs: {PET_STORE_URLS}")
    app.run(host='0.0.0.0', port=8080, debug=True)
