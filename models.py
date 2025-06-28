

# models.py

import os
import httpx
import logging
import asyncio

# تنظیم لاگر
logger = logging.getLogger(__name__)

# تعریف دیکشنری MODELS
MODELS = {
    "gpt-4o": "openai/gpt-4o-2024-11-20",
    "Gemini 2.5 Flash": "google/gemini-2.5-flash-preview",
    "GPT-4.1 Mini": "openai/gpt-4.1-mini",
    # "o4 Mini High (search)": "openai/o4-mini-high"
    "perplexity": "perplexity/sonar-pro"
}

# دیکشنری مدل‌های رایگان
MODELS_FREE = {
    "Grok 3 Mini Beta": "x-ai/grok-3-mini-beta",
    "Gemini 2.5 Pro": "google/gemini-2.5-pro-exp-03-25",
    "Llama 4 Maverick": "meta-llama/llama-4-maverick:free",
    "Llama 4 Scout": "meta-llama/llama-4-scout:free"
}

# دیکشنری مدل‌های Thinking واقعی و قدرتمند
MODELS_THINKING = {
    # "Claude 3.7 Sonnet (Thinking)": "anthropic/claude-3.7-sonnet:thinking",
    "GPT-o3": "openai/o3",
    "Grok 3 Beta": "x-ai/grok-3-beta",
    "o3 Mini High": "openai/o3-mini-high",
    "o4 Mini High": "openai/o4-mini-high"
}

# دیکشنری مدل‌های multimodal برای آنالیز تصویر
MODELS_IMAGE_ANALYZE = {
    "gpt-4o-vision":        "openai/gpt-4o-2024-11-20",
    "gemini-2.5-flash-vision":  "google/gemini-2.5-flash-preview",
    "gemini-2.5-pro-vision":    "google/gemini-2.5-pro-exp-03-25:free"
}

class Model:
    def __init__(self, model_type='gpt-4o'):
        self.model_type = model_type
        self.api_key = os.getenv('OPENROUTER_API_KEY')
        if not self.api_key:
            raise ValueError("OPENROUTER_API_KEY environment variable not set")
        self.api_base = 'https://openrouter.ai/api/v1'
        logger.info(f"Model initialized with type: {self.model_type}")

    async def generate_response(self, prompt, image_url=None, conversation_history=None):
        return await self._generate_openrouter_response(prompt, image_url, conversation_history)

    async def _generate_openrouter_response(self, prompt, image_url=None, conversation_history=None, retries=3, backoff_in_seconds=2):
        try:
            headers = {
                'Authorization': f'Bearer {self.api_key}',
                'Content-Type': 'application/json',
            }
            data = {
                'model': self._get_model_name()
            }

            messages = []

            # افزودن تاریخچه مکالمه (در صورت وجود)
            if conversation_history:
                messages.extend(conversation_history)

            # آماده‌سازی پیام کاربر
            # if self.model_type == 'gpt-4o' and image_url:
            if self.model_type in MODELS_IMAGE_ANALYZE and image_url:
                # برای مدل‌های ویژن، متن و تصویر را شامل می‌شود
                user_message_content = [
                    {
                        'type': 'text',
                        'text': prompt
                    },
                    {
                        'type': 'image_url',
                        'image_url': {
                            'url': image_url
                        }
                    }
                ]
                logger.info("Preparing messages with image_url for gpt-4o.")
            else:
                # برای مدل‌های متنی، فقط متن
                user_message_content = prompt
                logger.info("Preparing messages without image.")

            messages.append({
                'role': 'user',
                'content': user_message_content
            })

            data['messages'] = messages

            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f'{self.api_base}/chat/completions',
                    headers=headers,
                    json=data
                )
                response.raise_for_status()
                response_json = response.json()

                if 'choices' in response_json and response_json['choices']:
                    logger.info("Response received from OpenRouter API.")
                    return response_json['choices'][0]['message']['content'].strip()
                else:
                    logger.error(f"Unexpected response format: {response_json}")
                    return "An unexpected error occurred while processing the response."

        except httpx.HTTPStatusError as http_err:
            logger.error(f"HTTP error occurred: {http_err}")
            if http_err.response.status_code == 422:
                # مدیریت خطای Unprocessable Entity
                try:
                    error_message = http_err.response.json().get('error', {}).get('message', '')
                    logger.error(f"API Error Message: {error_message}")
                except:
                    pass
                return "An unexpected error occurred while processing the response."
            elif http_err.response.status_code == 429:
                if retries > 0:
                    logger.warning(f"Rate limited. Retrying after {backoff_in_seconds} seconds...")
                    await asyncio.sleep(backoff_in_seconds)
                    return await self._generate_openrouter_response(prompt, image_url, conversation_history, retries - 1, backoff_in_seconds * 2)
                else:
                    return "You have reached the rate limit. Please try again later."
            else:
                try:
                    logger.error(f"API Response: {http_err.response.text}")
                except:
                    pass
                return "An error occurred while contacting the language model service."
        except Exception as e:
            logger.error(f"An unexpected error occurred: {e}", exc_info=True)
            return "An unexpected error occurred."
    #------------------------------------------------------------------------------------


    def _get_model_name(self):
        """
        بر اساس نوع مدل (model_type) در self، نام مدل مربوطه از دیکشنری‌های MODELS،
        MODELS_FREE، MODELS_THINKING یا MODELS_ALLOW_FILE_QA استخراج می‌شود. در صورت عدم تطابق، یک خطا ایجاد می‌شود.
        """
        if self.model_type in MODELS:
            logger.info(f"Model name resolved: {MODELS[self.model_type]}")
            return MODELS[self.model_type]
        elif self.model_type in MODELS_FREE:
            logger.info(f"Free model name resolved: {MODELS_FREE[self.model_type]}")
            return MODELS_FREE[self.model_type]
        elif self.model_type in MODELS_THINKING:
            logger.info(f"Thinking model name resolved: {MODELS_THINKING[self.model_type]}")
            return MODELS_THINKING[self.model_type]
        elif self.model_type in MODELS_IMAGE_ANALYZE:
            logger.info(f"File-QA model name resolved: {MODELS_IMAGE_ANALYZE[self.model_type]}")
            return MODELS_IMAGE_ANALYZE[self.model_type]
        else:
            logger.error("Unsupported model type.")
            raise ValueError("Unsupported model type.")



    # def _get_model_name(self):
    #     """
    #     بر اساس نوع مدل (model_type) در self، نام مدل مربوطه از دیکشنری‌های MODELS،
    #     MODELS_FREE یا MODELS_THINKING استخراج می‌شود. در صورت عدم تطابق، یک خطا ایجاد می‌شود.
    #     """
    #     if self.model_type in MODELS:
    #         logger.info(f"Model name resolved: {MODELS[self.model_type]}")
    #         return MODELS[self.model_type]
    #     elif self.model_type in MODELS_FREE:
    #         logger.info(f"Free model name resolved: {MODELS_FREE[self.model_type]}")
    #         return MODELS_FREE[self.model_type]
    #     elif self.model_type in MODELS_THINKING:
    #         logger.info(f"Thinking model name resolved: {MODELS_THINKING[self.model_type]}")
    #         return MODELS_THINKING[self.model_type]
    #     else:
    #         logger.error("Unsupported model type.")
    #         raise ValueError("Unsupported model type.")



    # def _get_model_name(self):
    #     """
    #     بر اساس نوع مدل (model_type) در self، نام مدل مربوطه از دیکشنری MODELS
    #     یا MODELS_FREE استخراج می‌شود. در صورت عدم تطابق، یک خطا ایجاد می‌شود.
    #     """
    #     if self.model_type in MODELS:
    #         logger.info(f"Model name resolved: {MODELS[self.model_type]}")
    #         return MODELS[self.model_type]
    #     elif self.model_type in MODELS_FREE:
    #         logger.info(f"Free model name resolved: {MODELS_FREE[self.model_type]}")
    #         return MODELS_FREE[self.model_type]
    #     else:
    #         logger.error("Unsupported model type.")
    #         raise ValueError("Unsupported model type.")
    
    
    

    