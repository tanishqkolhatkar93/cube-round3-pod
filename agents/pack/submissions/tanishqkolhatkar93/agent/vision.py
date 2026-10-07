import os
import json
import traceback
from google import genai
from google.genai import types
from schemas import AIAnalysisResult


def get_client():
    return genai.Client()


def analyze_package_image(image_bytes: bytes, expected_order_lines: str) -> AIAnalysisResult:
    prompt = """You are a highly precise Amazon Fulfillment Pack Manager AI.
Your job is to verify the contents of an open shipping box before it is sealed.

EXPECTED ORDER LINES: {expected_order_lines}

INSTRUCTIONS:
1. Carefully examine the image of the open box.
2. Identify every single product and its quantity.
3. Compare what you see EXACTLY against the expected order lines.
4. You must output a strictly structured JSON matching the schema provided.

VERDICT RULES:
- SEAL: Only if all items are present, quantities are correct, and there are NO extra items.
- STOP_AND_FIX: If any item is missing, there is an extra item, or a quantity is wrong.
- UNCERTAIN: If the image is blurry, an item is heavily occluded. Do NOT guess if you are unsure."""
    prompt = prompt.replace("{expected_order_lines}", expected_order_lines)
    try:
        client = get_client()
        model_name = os.getenv('VISION_MODEL', 'gemini-flash-lite-latest')
        image_part = types.Part.from_bytes(data=image_bytes, mime_type='image/jpeg')
        response = client.models.generate_content(
            model=model_name,
            contents=[prompt, image_part],
            config=types.GenerateContentConfig(
                response_mime_type='application/json',
                response_schema=AIAnalysisResult,
                temperature=0.1,
            )
        )
        result_json = json.loads(response.text)
        return AIAnalysisResult(**result_json)
    except Exception as e:
        print(f'VISION ENGINE ERROR: {str(e)}')
        traceback.print_exc()
        raise e
