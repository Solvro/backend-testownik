from rest_framework import serializers

from .models import BlogPost


class BlogPostListSerializer(serializers.ModelSerializer):
    author_name = serializers.CharField(source="author.full_name", default=None)

    class Meta:
        model = BlogPost
        fields = ["id", "title", "slug", "excerpt", "published_at", "author_name"]


class BlogPostDetailSerializer(BlogPostListSerializer):
    class Meta(BlogPostListSerializer.Meta):
        fields = BlogPostListSerializer.Meta.fields + ["content", "created_at", "updated_at"]
