```python
# This script implements semantic retrieval using TF-IDF for finding relevant past solutions by keyword.
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

class SemanticRetrieval:
    def __init__(self):
        self.vectorizer = TfidfVectorizer()
        self.documents = []
    
    def add_document(self, document):
        """Add a new document to the corpus."""
        self.documents.append(document)
    
    def retrieve_top_n(self, query, n=3):
        """Retrieve top-n similar documents based on cosine similarity."""
        if not self.documents:
            return []
        
        # Vectorize all documents and the query
        tfidf_matrix = self.vectorizer.fit_transform(self.documents + [query])
        query_vector = tfidf_matrix[-1]
        
        # Calculate cosine similarity between the query vector and document vectors
        similarities = cosine_similarity(query_vector, tfidf_matrix[:-1]).flatten()
        
        # Get indices of top-n most similar documents
        top_indices = similarities.argsort()[-n:][::-1]
        
        return [self.documents[i] for i in top_indices]

# Example usage:
if __name__ == "__main__":
    sr = SemanticRetrieval()
    sr.add_document("Solved a problem using machine learning.")
    sr.add_document("Fixed a bug by updating the codebase.")
    sr.add_document("Implemented a feature request for the app.")
    
    query = "How to solve a similar machine learning problem?"
    top_results = sr.retrieve_top_n(query)
    print("Top results:", top_results)
```