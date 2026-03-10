from django.conf import settings
from pymongo import MongoClient


class MongoService:
    @staticmethod
    def _get_client() -> MongoClient | None:
        if not settings.MONGODB_URI:
            return None
        return MongoClient(settings.MONGODB_URI, serverSelectionTimeoutMS=3000)

    @classmethod
    def _get_collection(cls, name: str):
        client = cls._get_client()
        if client is None:
            return None
        return client[settings.MONGODB_DB_NAME][name]

    @staticmethod
    def ping() -> dict:
        if not settings.MONGODB_URI:
            return {'ok': False, 'message': 'MONGODB_URI is not configured.'}
        try:
            client = MongoClient(settings.MONGODB_URI, serverSelectionTimeoutMS=3000)
            client.admin.command('ping')
            return {'ok': True, 'message': f'MongoDB connected: {settings.MONGODB_DB_NAME}'}
        except Exception as exc:
            return {'ok': False, 'message': str(exc)}

    @classmethod
    def insert_conversation_log(
        cls,
        *,
        session_id: int,
        world_id: int,
        character_id: int,
        user_input: str,
        ai_output: str,
    ) -> dict:
        collection = cls._get_collection('conversation_logs')
        if collection is None:
            return {'ok': False, 'message': 'MONGODB_URI is not configured.'}
        try:
            result = collection.insert_one(
                {
                    'session_id': session_id,
                    'world_id': world_id,
                    'character_id': character_id,
                    'user_input': user_input,
                    'ai_output': ai_output,
                }
            )
            return {'ok': True, 'id': str(result.inserted_id)}
        except Exception as exc:
            return {'ok': False, 'message': str(exc)}

    @classmethod
    def get_conversation_history(cls, *, session_id: int, limit: int = 8) -> list[dict]:
        collection = cls._get_collection('conversation_logs')
        if collection is None:
            return []
        docs = (
            collection.find({'session_id': session_id}, {'_id': 0, 'user_input': 1, 'ai_output': 1})
            .sort('_id', -1)
            .limit(limit)
        )
        history = list(docs)
        history.reverse()
        return history
