"""
Fonctions utilitaires pour le traitement de texte
"""

import re
from typing import List


def is_empty(text: str) -> bool:
    """
    Vérifie si une chaîne est vide ou None
    
    Args:
        text: Texte à vérifier
        
    Returns:
        True si le texte est vide ou None
    """
    return text is None or text.strip() == ""


def chunk_text_by_words(text: str, max_words: int) -> List[str]:
    """
    Découpe un texte en chunks de taille maximale en nombre de mots
    
    Args:
        text: Texte à découper
        max_words: Nombre maximum de mots par chunk
        
    Returns:
        Liste de chunks
    """
    if is_empty(text):
        return []
    
    words = text.split()
    
    if len(words) <= max_words:
        return [text]
    
    chunks = []
    current_chunk = []
    current_count = 0
    
    for word in words:
        current_chunk.append(word)
        current_count += 1
        
        if current_count >= max_words:
            chunks.append(" ".join(current_chunk))
            current_chunk = []
            current_count = 0
    
    # Ajoute le dernier chunk s'il reste des mots
    if current_chunk:
        chunks.append(" ".join(current_chunk))
    
    return chunks


def trim_to_word_limit(text: str, max_words: int) -> str:
    """
    Tronque un texte pour ne garder que les N premiers mots
    
    Args:
        text: Texte à tronquer
        max_words: Nombre maximum de mots
        
    Returns:
        Texte tronqué
    """
    if is_empty(text):
        return text
    
    words = text.split()
    
    if len(words) <= max_words:
        return text
    
    return " ".join(words[:max_words])


def count_words(text: str) -> int:
    """
    Compte le nombre de mots dans un texte
    
    Args:
        text: Texte à analyser
        
    Returns:
        Nombre de mots
    """
    if is_empty(text):
        return 0
    return len(text.split())


def extract_json_from_text(text: str) -> str:
    """
    Extrait un objet JSON d'un texte qui peut contenir autre chose
    
    Args:
        text: Texte contenant potentiellement du JSON
        
    Returns:
        String JSON extrait ou le texte original si pas de JSON trouvé
    """
    # Cherche un objet JSON dans le texte
    json_match = re.search(r'\{.*\}', text, re.DOTALL)
    if json_match:
        return json_match.group(0)
    return text


def clean_whitespace(text: str) -> str:
    """
    Nettoie les espaces excessifs dans un texte
    
    Args:
        text: Texte à nettoyer
        
    Returns:
        Texte nettoyé
    """
    if is_empty(text):
        return text
    
    # Remplace les espaces multiples par un seul
    text = re.sub(r'\s+', ' ', text)
    
    # Retire les espaces en début et fin
    text = text.strip()
    
    return text
