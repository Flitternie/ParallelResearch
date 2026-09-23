# ADOBE CONFIDENTIAL
#
# Copyright 2026 Adobe
# All Rights Reserved.
#
# NOTICE: All information contained herein is, and remains
# the property of Adobe and its suppliers, if any. The intellectual
# and technical concepts contained herein are proprietary to Adobe
# and its suppliers and are protected by all applicable intellectual
# property laws, including trade secret and copyright laws.
# Dissemination of this information or reproduction of this material
# is strictly forbidden unless prior written permission is obtained
# from Adobe.

from langchain_community.document_loaders import DirectoryLoader, PyPDFLoader
from langchain.text_splitter import CharacterTextSplitter
from langchain_core.embeddings import Embeddings
from langchain_community.vectorstores import FAISS
from openai import OpenAI


class CustomEmbeddings(Embeddings):
    def __init__(self, model: str, base_url: str, api_key: str = None, chunk_size: int = 1000, 
                 max_retries: int = 2, request_timeout: float = None):
        self.model = model
        self.base_url = base_url
        self.api_key = api_key or None  # VLLM doesn't require real API key
        self.chunk_size = chunk_size
        self.max_retries = max_retries
        self.request_timeout = request_timeout
        
        # Initialize OpenAI client with custom base URL
        self.client = OpenAI(
            base_url=self.base_url,
            api_key=self.api_key,
            max_retries=self.max_retries,
            timeout=self.request_timeout
        )

    def _create_embeddings(self, texts: list[str]) -> list[list[float]]:
        """Internal method to create embeddings with proper error handling."""
        try:
            response = self.client.embeddings.create(
                input=texts,
                model=self.model
            )
            
            # Handle both dict and object responses
            if not isinstance(response, dict):
                response = response.model_dump()
            
            return [r["embedding"] for r in response["data"]]
        except Exception as e:
            print(f"Error creating embeddings: {e}")
            raise

    def embed_documents(self, texts: list[str], chunk_size: int = None) -> list[list[float]]:
        """Embed search docs.

        Args:
            texts: List of text to embed.
            chunk_size: Override default chunk size for this call.

        Returns:
            List of embeddings.
        """
        if not texts:
            return []
        
        chunk_size = chunk_size or self.chunk_size
        embeddings: list[list[float]] = []
        
        # Process texts in chunks to avoid API limits
        for i in range(0, len(texts), chunk_size):
            chunk = texts[i : i + chunk_size]
            chunk_embeddings = self._create_embeddings(chunk)
            embeddings.extend(chunk_embeddings)
        
        return embeddings

    def embed_query(self, text: str) -> list[float]:
        """Embed query text.

        Args:
            text: Text to embed.

        Returns:
            Embedding.
        """
        if not text.strip():
            # Handle empty text case
            return self._create_embeddings([""])[0]
        
        return self.embed_documents([text])[0]

    async def _acreate_embeddings(self, texts: list[str]) -> list[list[float]]:
        """Internal async method to create embeddings."""
        try:
            # Create async client if not exists
            if not hasattr(self, 'async_client'):
                from openai import AsyncOpenAI
                self.async_client = AsyncOpenAI(
                    base_url=self.base_url,
                    api_key=self.api_key,
                    max_retries=self.max_retries,
                    timeout=self.request_timeout
                )
            
            response = await self.async_client.embeddings.create(
                input=texts,
                model=self.model
            )
            
            # Handle both dict and object responses
            if not isinstance(response, dict):
                response = response.model_dump()
            
            return [r["embedding"] for r in response["data"]]
        except Exception as e:
            print(f"Error creating async embeddings: {e}")
            raise

    async def aembed_documents(self, texts: list[str], chunk_size: int = None) -> list[list[float]]:
        """Asynchronous Embed search docs.

        Args:
            texts: List of text to embed.
            chunk_size: Override default chunk size for this call.

        Returns:
            List of embeddings.
        """
        if not texts:
            return []
        
        chunk_size = chunk_size or self.chunk_size
        embeddings: list[list[float]] = []
        
        # Process texts in chunks to avoid API limits
        for i in range(0, len(texts), chunk_size):
            chunk = texts[i : i + chunk_size]
            chunk_embeddings = await self._acreate_embeddings(chunk)
            embeddings.extend(chunk_embeddings)
        
        return embeddings

    async def aembed_query(self, text: str) -> list[float]:
        """Asynchronous Embed query text.

        Args:
            text: Text to embed.

        Returns:
            Embedding.
        """
        if not text.strip():
            # Handle empty text case
            return (await self._acreate_embeddings([""]))[0]
        
        embeddings = await self.aembed_documents([text])
        return embeddings[0]

    def __repr__(self) -> str:
        return (f"CustomEmbeddings(model='{self.model}', "
                f"base_url='{self.base_url}', "
                f"chunk_size={self.chunk_size})")
    

def build_vector_db(directory_path: str = "./database", save_path: str = "vector_db") -> None:
    """Builds the vector database from PDF files in the specified directory."""

    # Create a DirectoryLoader instance, specifying the directory and the PDF loader
    loader = DirectoryLoader(directory_path, glob="**/*.pdf", loader_cls=PyPDFLoader)

    # Load the documents
    documents = loader.load()

    for d in documents:
        d.page_content = d.page_content.replace("\n", " ").strip()
    
    text_splitter = CharacterTextSplitter(chunk_size=200, chunk_overlap=30, separator=" ")
    docs = text_splitter.split_documents(documents=documents)

    vector_store = FAISS.from_documents(docs, CustomEmbeddings(model="nomic-ai/nomic-embed-text-v1", base_url="http://0.0.0.0:8000/v1"))

    vector_store.save_local("vector_db")

def load_vector_db(save_path: str = "vector_db") -> FAISS:
    """Loads the vector database from the specified path."""
    return FAISS.load_local(save_path, embeddings=CustomEmbeddings(model="nomic-ai/nomic-embed-text-v1", base_url="http://0.0.0.0:8000/v1"), allow_dangerous_deserialization=True)
