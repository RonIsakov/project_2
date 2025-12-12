# Pet Store REST API assignment 1 Ron Isakov, Noam Kyram
from flask import Flask, jsonify, request, make_response, send_file
import requests
import os
import re
from datetime import datetime
from pymongo import MongoClient, ReturnDocument

# MongoDB Connection
MONGO_URI = os.getenv('MONGO_URI', 'mongodb://mongodb:27017/')
STORE_ID = os.getenv('STORE_ID', '1')

# Connect to MongoDB
client = MongoClient(MONGO_URI)
db = client['petstore_db']

# Collections - separate for each store
pet_types_collection = db[f'pet_types_store{STORE_ID}']
pets_collection = db[f'pets_store{STORE_ID}']

# Global image counter for unique filenames
global IMG_N
IMG_N = 0

def genID():
    """
    Generate unique pet-type ID using MongoDB counter.
    Survives restarts and prevents ID collisions.
    """
    counters_collection = db['counters']
    result = counters_collection.find_one_and_update(
        {'_id': f'pet_type_id_store{STORE_ID}'},
        {'$inc': {'sequence': 1}},
        upsert=True,
        return_document=ReturnDocument.AFTER
    )
    return str(result['sequence'])

def genImageFilename(pet_name, extension):
    """Generate a unique filename for images"""
    global IMG_N
    IMG_N += 1
    return f"{pet_name}_{IMG_N}.{extension}"

# Initialize Flask app
app = Flask(__name__)

# Directory to store pet pictures
PICTURES_DIR = "pictures"
if not os.path.exists(PICTURES_DIR):
    os.makedirs(PICTURES_DIR)

# Get Ninja API key from environment variable
NINJA_API_KEY = os.environ.get('NINJA_API_KEY', '')


def call_ninja_api(animal_name):
    """
    Call Ninja Animals API and return parsed data for the given animal name.

    Returns: (dict, error_code) where dict has keys: type, family, genus, attributes, lifespan
             Returns (None, error_code) if animal not found or API error
    """
    try:
        api_url = f'https://api.api-ninjas.com/v1/animals?name={animal_name}'
        headers = {'X-Api-Key': NINJA_API_KEY}

        response = requests.get(api_url, headers=headers)

        # Check for API errors
        if response.status_code != 200:
            return None, response.status_code

        data = response.json()

        # If no results returned
        if not data or len(data) == 0:
            return None, None

        animal_data = None
        for item in data:
            if item.get('name', '').lower() == animal_name.lower():
                animal_data = item
                break

        # If no exact match found, return None (animal not found)
        if not animal_data:
            return None, None

        # Extract taxonomy info
        taxonomy = animal_data.get('taxonomy', {})
        family = taxonomy.get('family', '')
        genus = taxonomy.get('genus', '')

        # Extract characteristics
        characteristics = animal_data.get('characteristics', {})

        # Get attributes from temperament or group_behavior
        # Priority: temperament > group_behavior
        attributes = []
        temperament = characteristics.get('temperament', '')
        group_behavior = characteristics.get('group_behavior', '')

        if temperament:
            # Split temperament into words, remove punctuation
            attributes = re.findall(r'\b\w+\b', temperament)
        elif group_behavior:
            # Split group_behavior into words, remove punctuation
            attributes = re.findall(r'\b\w+\b', group_behavior)

        # Get lifespan and parse it
        lifespan_str = characteristics.get('lifespan', '')
        lifespan = parse_lifespan(lifespan_str)

        return {
            'type': animal_data.get('name', ''),
            'family': family,
            'genus': genus,
            'attributes': attributes,
            'lifespan': lifespan
        }, None

    except Exception as e:
        print(f"Error calling Ninja API: {str(e)}")
        return None, 500


def parse_lifespan(lifespan_str):
    """
    Parse lifespan string and return the lowest number.
    Returns: integer or None if no number found
    """
    if not lifespan_str:
        return None

    # Find all numbers in the string
    numbers = re.findall(r'\d+', lifespan_str)

    if not numbers:
        return None

    # Convert to integers and return the LOWEST (per assignment requirements)
    return min(int(num) for num in numbers)

def download_and_save_image(image_url, pet_name):
    """
    Download image from URL and save it to disk.
    Images are stored temporarily during runtime - non-persistent.
    Returns: filename if successful, None if failed
    """
    try:
        response = requests.get(image_url, timeout=10)

        if response.status_code != 200:
            print(f"Failed to download image from {image_url}")
            return None

        # Determine file extension from Content-Type or URL
        content_type = response.headers.get('Content-Type', '')
        if 'jpeg' in content_type or 'jpg' in content_type:
            extension = 'jpg'
        elif 'png' in content_type:
            extension = 'png'
        else:
            # Try to get extension from URL
            url_ext = image_url.split('.')[-1].lower()
            if url_ext in ['jpg', 'jpeg', 'png']:
                extension = url_ext if url_ext != 'jpeg' else 'jpg'
            else:
                extension = 'jpg'  # Default to jpg

        # Create unique filename using global counter
        filename = genImageFilename(pet_name, extension)
        filepath = os.path.join(PICTURES_DIR, filename)

        # Save image to disk (temporary, lost when container stops)
        with open(filepath, 'wb') as f:
            f.write(response.content)

        print(f"Image saved: {filename}")
        return filename

    except Exception as e:
        print(f"Error downloading image: {str(e)}")
        return None


def delete_image_file(filename):
    """
    Delete image file from disk if it exists.
    """
    try:
        if filename and filename != "NA":
            filepath = os.path.join(PICTURES_DIR, filename)
            if os.path.exists(filepath):
                os.remove(filepath)
                print(f"Image deleted: {filename}")
    except Exception as e:
        print(f"Error deleting image: {str(e)}")


def parse_date(date_string):
    """
    Parse date string in DD-MM-YYYY format.
    Returns: datetime object or None if invalid
    """
    try:
        if not date_string or date_string == "NA":
            return None
        return datetime.strptime(date_string, "%d-%m-%Y")
    except Exception as e:
        print(f"Error parsing date {date_string}: {str(e)}")
        return None


def compare_dates(date_str1, date_str2, comparison):
    """
    Compare two date strings.
    Returns: True if comparison is satisfied, False otherwise
    """
    date1 = parse_date(date_str1)
    date2 = parse_date(date_str2)

    if not date1 or not date2:
        return False

    if comparison == 'GT':
        return date1 > date2
    elif comparison == 'LT':
        return date1 < date2
    else:
        return False

#Pet-Types Collection Endpoints
@app.route('/pet-types', methods=['POST'])
def add_pet_type():
    """Create a new pet-type by calling Ninja API"""
    print("POST /pet-types")
    try:
        # Validate Content-Type
        content_type = request.headers.get('Content-Type')
        if content_type != 'application/json':
            return jsonify({"error": "Expected application/json media type"}), 415

        data = request.get_json()

        # Check if required 'type' field is present
        if 'type' not in data:
            return jsonify({"error": "Malformed data"}), 400

        animal_type = data['type']

        # Check if pet-type already exists in MongoDB
        existing_pet_type = pet_types_collection.find_one(
            {"type": {"$regex": f"^{animal_type}$", "$options": "i"}}
        )
        if existing_pet_type:
            return jsonify({"error": "Malformed data"}), 400

        # Call Ninja API to get animal information
        animal_info, error_code = call_ninja_api(animal_type)

        if animal_info is None:
            if error_code:
                # API returned an error status code
                return jsonify({"server error": f"API response code {error_code}"}), 500
            else:
                # Animal not found (no exact match)
                return jsonify({"error": "Malformed data"}), 400

        # Generate unique ID
        new_id = genID()

        # Create pet-type object
        pet_type_obj = {
            "id": new_id,
            "type": animal_info['type'],
            "family": animal_info['family'],
            "genus": animal_info['genus'],
            "attributes": animal_info['attributes'],
            "lifespan": animal_info['lifespan'],
            "pets": []  # Empty array initially
        }

        # Store in MongoDB
        pet_types_collection.insert_one(pet_type_obj)

        print(f"Created pet-type in Store {STORE_ID}: {pet_type_obj}")
        return jsonify(pet_type_obj), 201

    except Exception as e:
        print(f"Exception in add_pet_type: {str(e)}")
        return jsonify({"server error": str(e)}), 500

@app.route('/pet-types', methods=['GET'])
def get_pet_types():
    """Get all pet-types with optional filtering"""
    print("GET /pet-types")
    try:
        # Get query parameters
        query_params = request.args.to_dict()
        print(f"query_params = {query_params}")

        # If no query parameters, return all pet-types from MongoDB
        if not query_params:
            pet_types = list(pet_types_collection.find({}, {'_id': 0}))
            return jsonify(pet_types), 200

        # Fetch all pet-types from MongoDB
        all_pet_types = list(pet_types_collection.find({}, {'_id': 0}))

        # Filter pet-types based on query parameters
        results = []

        for pet_type in all_pet_types:
            matches = True

            # Check each query parameter
            for key, value in query_params.items():
                if key == 'hasAttribute':
                    # check if any attribute matches
                    attribute_match = False
                    for attr in pet_type.get('attributes', []):
                        if attr.lower() == value.lower():
                            attribute_match = True
                            break
                    if not attribute_match:
                        matches = False
                        break
                else:
                    # Regular field comparison
                    # Handle None/null values
                    pet_type_value = pet_type.get(key)
                    if pet_type_value is None:
                        # If field is None, convert to string "none" for comparison
                        if str(pet_type_value).lower() != value.lower():
                            matches = False
                            break
                    else:
                        # Convert to string and compare
                        if str(pet_type_value).lower() != value.lower():
                            matches = False
                            break

            if matches:
                results.append(pet_type)

        print(f"results = {results}")
        return jsonify(results), 200

    except Exception as e:
        print(f"Exception in get_pet_types: {str(e)}")
        return jsonify({"server error": str(e)}), 500


# Pet-Types Individual Endpoints
@app.route('/pet-types/<string:pet_type_id>', methods=['GET'])
def get_pet_type(pet_type_id):
    """Get a specific pet-type by ID"""
    print(f"GET /pet-types/{pet_type_id}")
    try:
        # Find in MongoDB
        pet_type = pet_types_collection.find_one({"id": pet_type_id}, {'_id': 0})

        if not pet_type:
            return jsonify({"error": "Not found"}), 404

        print(f"Found pet-type: {pet_type}")
        return jsonify(pet_type), 200

    except Exception as e:
        print(f"Exception in get_pet_type: {str(e)}")
        return jsonify({"server error": str(e)}), 500

@app.route('/pet-types/<string:pet_type_id>', methods=['DELETE'])
def delete_pet_type(pet_type_id):
    """Delete a specific pet-type by ID"""
    print(f"DELETE /pet-types/{pet_type_id}")
    try:
        # Validate pet_type_id
        if not pet_type_id or pet_type_id.strip() == "":
            return jsonify({"error": "Malformed data"}), 400

        # Find pet-type in MongoDB
        pet_type = pet_types_collection.find_one({"id": pet_type_id}, {'_id': 0})

        if not pet_type:
            return jsonify({"error": "Not found"}), 404

        # Check if the 'pets' field is not empty
        if pet_type['pets']:
            print(f"Cannot delete pet-type {pet_type_id}: pets array is not empty")
            return jsonify({"error": "Malformed data"}), 400

        # Delete from MongoDB
        result = pet_types_collection.delete_one({"id": pet_type_id})

        if result.deleted_count == 0:
            return jsonify({"error": "Not found"}), 404

        print(f"Deleted pet-type {pet_type_id}")
        return '', 204

    except Exception as e:
        print(f"Exception in delete_pet_type: {str(e)}")
        return jsonify({"server error": str(e)}), 500


# Pets Collection Endpoints
@app.route('/pet-types/<string:pet_type_id>/pets', methods=['POST'])
def add_pet(pet_type_id):
    """Add a new pet to a pet-type"""
    print(f"POST /pet-types/{pet_type_id}/pets")
    try:
        # Validate Content-Type
        content_type = request.headers.get('Content-Type')
        if content_type != 'application/json':
            return jsonify({"error": "Expected application/json media type"}), 415

        # Check if pet-type exists
        pet_type = pet_types_collection.find_one({"id": pet_type_id}, {'_id': 0})

        if not pet_type:
            return jsonify({"error": "Not found"}), 404

        data = request.get_json()

        # Check if required 'name' field is present and not empty
        if 'name' not in data or not data['name'] or not data['name'].strip():
            return jsonify({"error": "Malformed data"}), 400

        pet_name = data['name']

        # Check if pet name already exists (case-insensitive)
        existing_pet = pets_collection.find_one({
            "pet_type_id": pet_type_id,
            "name": {"$regex": f"^{pet_name}$", "$options": "i"}
        })

        if existing_pet:
            return jsonify({"error": "Malformed data"}), 400

        # Optional fields: birthdate, picture_url
        birthdate = data.get('birthdate', None)
        picture_url = data.get('picture-url', None)

        # Validate birthdate format if provided
        if birthdate != None:
            parsed_date = parse_date(birthdate)
            if not parsed_date:
                return jsonify({"error": "Malformed data"}), 400

        # Download and save image if picture_url is provided
        picture_filename = "NA"
        if picture_url:
            picture_filename = download_and_save_image(picture_url, pet_name)
            if not picture_filename:
                # Image download failed, but we continue with "NA"
                picture_filename = "NA"

        # Create pet object
        pet_obj = {
            "name": pet_name,
            "pet_type_id": pet_type_id,  # NEW: link to pet-type
            "birthdate": birthdate,
            "picture": picture_filename
        }

        # Store in MongoDB
        pets_collection.insert_one(pet_obj)

        # Update pet-type's pets array
        pet_types_collection.update_one(
            {"id": pet_type_id},
            {"$push": {"pets": pet_name}}
        )

        print(f"Created pet: {pet_obj}")
        # Remove pet_type_id from response
        response_obj = {"name": pet_name, "birthdate": birthdate, "picture": picture_filename}
        return jsonify(response_obj), 201

    except Exception as e:
        print(f"Exception in add_pet: {str(e)}")
        return jsonify({"server error": str(e)}), 500

@app.route('/pet-types/<string:pet_type_id>/pets', methods=['GET'])
def get_pets(pet_type_id):
    """Get all pets for a pet-type with optional filtering"""
    print(f"GET /pet-types/{pet_type_id}/pets")
    try:
        # Check if pet-type exists
        pet_type = pet_types_collection.find_one({"id": pet_type_id}, {'_id': 0})

        if not pet_type:
            return jsonify({"error": "Not found"}), 404

        # Get query parameters
        query_params = request.args.to_dict()
        print(f"query_params = {query_params}")

        # Get all pets for this pet-type from MongoDB
        pets_list = list(pets_collection.find(
            {"pet_type_id": pet_type_id},
            {'_id': 0, 'pet_type_id': 0}  # Exclude MongoDB _id and our pet_type_id link
        ))

        if not pets_list:
            return jsonify([]), 200

        # If no query parameters, return all pets
        if not query_params:
            return jsonify(pets_list), 200

        # Filter pets based on query parameters
        results = []

        for pet in pets_list:
            matches = True

            # Check each query parameter
            for key, value in query_params.items():
                if key == 'birthdateGT':
                    # Greater than comparison for birthdate
                    if not compare_dates(pet.get('birthdate', 'NA'), value, 'GT'):
                        matches = False
                        break
                elif key == 'birthdateLT':
                    # Less than comparison for birthdate
                    if not compare_dates(pet.get('birthdate', 'NA'), value, 'LT'):
                        matches = False
                        break
                elif key == 'name':
                    # Name comparison (case-insensitive)
                    if pet.get('name', '').lower() != value.lower():
                        matches = False
                        break
                else:
                    # Regular field comparison (case-insensitive)
                    pet_value = pet.get(key)
                    if pet_value is None:
                        if str(pet_value).lower() != value.lower():
                            matches = False
                            break
                    else:
                        if str(pet_value).lower() != value.lower():
                            matches = False
                            break

            if matches:
                results.append(pet)

        print(f"results = {results}")
        return jsonify(results), 200

    except Exception as e:
        print(f"Exception in get_pets: {str(e)}")
        return jsonify({"server error": str(e)}), 500


# Pets Individual Endpoints
@app.route('/pet-types/<string:pet_type_id>/pets/<string:pet_name>', methods=['GET'])
def get_pet(pet_type_id, pet_name):
    """Get a specific pet by name"""
    print(f"GET /pet-types/{pet_type_id}/pets/{pet_name}")
    try:
        # Check if pet-type exists
        pet_type = pet_types_collection.find_one({"id": pet_type_id}, {'_id': 0})

        if not pet_type:
            return jsonify({"error": "Not found"}), 404

        # Find pet in MongoDB
        pet = pets_collection.find_one(
            {"pet_type_id": pet_type_id, "name": pet_name},
            {'_id': 0, 'pet_type_id': 0}
        )

        if not pet:
            return jsonify({"error": "Not found"}), 404

        print(f"Found pet: {pet}")
        return jsonify(pet), 200

    except Exception as e:
        print(f"Exception in get_pet: {str(e)}")
        return jsonify({"server error": str(e)}), 500

@app.route('/pet-types/<string:pet_type_id>/pets/<string:pet_name>', methods=['PUT'])
def update_pet(pet_type_id, pet_name):
    """Update a specific pet"""
    print(f"PUT /pet-types/{pet_type_id}/pets/{pet_name}")
    try:
        # Validate Content-Type
        content_type = request.headers.get('Content-Type')
        if content_type != 'application/json':
            return jsonify({"error": "Expected application/json media type"}), 415

        # Check if pet-type exists
        pet_type = pet_types_collection.find_one({"id": pet_type_id}, {'_id': 0})

        if not pet_type:
            return jsonify({"error": "Not found"}), 404

        # Find current pet
        current_pet = pets_collection.find_one(
            {"pet_type_id": pet_type_id, "name": pet_name},
            {'_id': 0, 'pet_type_id': 0}
        )

        if not current_pet:
            return jsonify({"error": "Not found"}), 404

        data = request.get_json()

        # Check if required 'name' field is present and not empty
        if 'name' not in data or not data['name'] or not data['name'].strip():
            return jsonify({"error": "Malformed data"}), 400

        payload_name = data['name']

        # Validate that the name in the URL matches the name in the payload
        if payload_name != pet_name:
            return jsonify({"error": "Malformed data"}), 400

        # Optional fields: birthdate, picture_url
        # If not provided, keep the current values
        birthdate = data.get('birthdate', current_pet.get('birthdate', 'NA'))
        picture_url = data.get('picture_url', None)

        # Validate birthdate format if provided and not "NA"
        if birthdate != 'NA':
            parsed_date = parse_date(birthdate)
            if not parsed_date:
                return jsonify({"error": "Malformed data"}), 400

        # Handle picture update
        old_picture = current_pet.get('picture', 'NA')
        picture_filename = old_picture

        if picture_url:
            # Delete old picture if it exists
            if old_picture and old_picture != "NA":
                delete_image_file(old_picture)

            # Download new picture
            picture_filename = download_and_save_image(picture_url, pet_name)
            if not picture_filename:
                # Image download failed, use "NA"
                picture_filename = "NA"

        # Create updated pet object
        updated_pet = {
            "name": pet_name,
            "pet_type_id": pet_type_id,
            "birthdate": birthdate,
            "picture": picture_filename
        }

        # Update in MongoDB
        pets_collection.update_one(
            {"pet_type_id": pet_type_id, "name": pet_name},
            {"$set": updated_pet}
        )

        print(f"Updated pet: {updated_pet}")
        # Remove pet_type_id from response
        response_obj = {"name": pet_name, "birthdate": birthdate, "picture": picture_filename}
        return jsonify(response_obj), 200

    except Exception as e:
        print(f"Exception in update_pet: {str(e)}")
        return jsonify({"server error": str(e)}), 500

@app.route('/pet-types/<string:pet_type_id>/pets/<string:pet_name>', methods=['DELETE'])
def delete_pet(pet_type_id, pet_name):
    """Delete a specific pet"""
    print(f"DELETE /pet-types/{pet_type_id}/pets/{pet_name}")
    try:
        # Check if pet-type exists
        if pet_type_id not in PetTypes:
            return jsonify({"error": "Not found"}), 404

        # Check if pet exists for this pet-type
        if pet_type_id not in Pets or pet_name not in Pets[pet_type_id]:
            return jsonify({"error": "Not found"}), 404

        # Get the pet object to delete its image
        pet_obj = Pets[pet_type_id][pet_name]
        picture = pet_obj.get('picture')

        # Delete the pet's image file if it exists
        if picture and picture != "NA":
            delete_image_file(picture)

        # Remove pet from Pets dictionary
        del Pets[pet_type_id][pet_name]

        # Remove pet name from the pet-type's pets array
        PetTypes[pet_type_id]['pets'].remove(pet_name)

        print(f"Deleted pet {pet_name} from pet-type {pet_type_id}")
        return '', 204

    except Exception as e:
        print(f"Exception in delete_pet: {str(e)}")
        return jsonify({"server error": str(e)}), 500


# Pictures Endpoint
@app.route('/pictures/<string:file_name>', methods=['GET'])
def get_picture(file_name):
    """Get a picture file"""
    print(f"GET /pictures/{file_name}")
    try:
        # Build the full file path
        filepath = os.path.join(PICTURES_DIR, file_name)

        # Check if file exists
        if not os.path.exists(filepath):
            return jsonify({"error": "Not found"}), 404

        # Determine the Content-Type based on file extension
        file_ext = file_name.split('.')[-1].lower()
        if file_ext in ['jpg', 'jpeg']:
            content_type = 'image/jpeg'
        elif file_ext == 'png':
            content_type = 'image/png'
        else:
            # Default to jpeg if extension is unknown
            content_type = 'image/jpeg'

        # Return the image file
        return send_file(filepath, mimetype=content_type)

    except Exception as e:
        print(f"Exception in get_picture: {str(e)}")
        return jsonify({"server error": str(e)}), 500

if __name__ == '__main__':
    print("Starting Pet Store API server...")
    print(f"Ninja API Key configured: {'Yes' if NINJA_API_KEY else 'No'}")
    app.run(host='0.0.0.0', port=5001, debug=True)
