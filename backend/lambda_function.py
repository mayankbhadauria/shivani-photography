import os
import sys
import json
import traceback

sys.path.insert(0, os.path.dirname(__file__))

def lambda_handler(event, context):

    try:
        print(f"Event received: {json.dumps(event)}")
        print(f"Python path: {sys.path}")
        print(f"Environment variables: {dict(os.environ)}")

        # Try importing
        from mangum import Mangum
        print("Mangum imported successfully")

        from main import app
        print("Main app imported successfully")
        handler = Mangum(app, lifespan="off", api_gateway_base_path="/prod")
        print("Mangum handler created successfully")
        result = handler(event, context)
        print(f"Handler result: {result}")
        return result

    except Exception as e:
        error_msg = f"Lambda error: {str(e)}"
        print(error_msg)
        print(f"Traceback: {traceback.format_exc()}")
        return {
            'statusCode': 500,
            'headers': {
                'Content-Type': 'application/json',
                'Access-Control-Allow-Origin': '*'
            },
            'body': json.dumps({
                'error': error_msg,
                'traceback': traceback.format_exc()
            })
        }