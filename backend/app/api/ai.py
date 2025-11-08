"""
AI Services API Endpoints
- Caption generation
- Image analysis
- Style suggestions
"""

from fastapi import APIRouter, UploadFile, File, HTTPException
from pydantic import BaseModel
from typing import Optional, List
import anthropic
from app.config import settings

router = APIRouter()


class CaptionRequest(BaseModel):
    """Request model for caption generation"""
    content_type: str  # "lifestyle", "brand", "artist", "educator", "influencer"
    style_tone: Optional[str] = "casual"
    keywords: Optional[List[str]] = []
    image_description: Optional[str] = None


class CaptionResponse(BaseModel):
    """Response model for generated caption"""
    caption: str
    hashtags: List[str]
    suggestions: List[str]


@router.post("/generate-caption", response_model=CaptionResponse)
async def generate_caption(request: CaptionRequest):
    """
    Generate AI-powered caption using Claude

    - **content_type**: Type of content creator (lifestyle, brand, etc.)
    - **style_tone**: Tone of voice (casual, professional, playful, etc.)
    - **keywords**: Optional keywords to include
    - **image_description**: Description of the image/video
    """

    if not settings.anthropic_api_key:
        raise HTTPException(
            status_code=500,
            detail="Anthropic API key not configured"
        )

    try:
        client = anthropic.Anthropic(api_key=settings.anthropic_api_key)

        prompt = f"""You are a social media expert helping a {request.content_type} creator.

Generate an engaging caption for a social media post with the following details:
- Content type: {request.content_type}
- Tone: {request.style_tone}
- Keywords to include: {', '.join(request.keywords) if request.keywords else 'none'}
- Image description: {request.image_description or 'not provided'}

Provide:
1. A compelling caption (2-3 sentences, authentic and engaging)
2. 5-10 relevant hashtags
3. 2-3 alternative caption suggestions

Format your response as JSON:
{{
    "caption": "main caption text",
    "hashtags": ["hashtag1", "hashtag2", ...],
    "suggestions": ["alternative 1", "alternative 2", ...]
}}
"""

        message = client.messages.create(
            model="claude-3-5-sonnet-20241022",
            max_tokens=1024,
            messages=[
                {"role": "user", "content": prompt}
            ]
        )

        # Parse Claude's response (assuming JSON format)
        import json
        response_text = message.content[0].text

        # Try to extract JSON from response
        if "```json" in response_text:
            json_str = response_text.split("```json")[1].split("```")[0].strip()
            result = json.loads(json_str)
        else:
            result = json.loads(response_text)

        return CaptionResponse(
            caption=result.get("caption", ""),
            hashtags=result.get("hashtags", []),
            suggestions=result.get("suggestions", [])
        )

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to generate caption: {str(e)}"
        )


@router.post("/analyze-image")
async def analyze_image(file: UploadFile = File(...)):
    """
    Analyze uploaded image for:
    - Color palette
    - Mood/tone
    - Subject detection
    - Style recommendations
    """

    # TODO: Implement image analysis with OpenCV
    # For now, return mock data

    return {
        "colors": ["#FF6B6B", "#4ECDC4", "#45B7D1"],
        "mood": "vibrant",
        "tone": "energetic",
        "subjects": ["person", "outdoor"],
        "style_match": "lifestyle",
        "recommendations": [
            "Add a warm filter to enhance sunset tones",
            "Consider cropping to focus on main subject"
        ]
    }


@router.get("/health")
async def ai_health_check():
    """Check if AI services are available"""
    has_api_key = bool(settings.anthropic_api_key)

    return {
        "status": "ok" if has_api_key else "not_configured",
        "anthropic_configured": has_api_key,
        "models_available": ["claude-3-5-sonnet"] if has_api_key else []
    }
