"""
Classe principale IA - Équivalent Python de la classe Java IA.java

Cette classe centralise tous les appels à l'API OpenAI pour:
- Génération de titres
- Résumés de texte
- Classification de news
- Génération d'embeddings

Maintient la même interface que la version Java pour faciliter l'intégration.
"""

import json
import logging
import re
import unicodedata
from pathlib import Path
from typing import List, Optional, Dict, Any, Tuple

from shared.enums import Policy

from .config_manager import ConfigManager
from .utils import chunk_text_by_words, trim_to_word_limit, is_empty
from .llm_providers import get_provider, BaseLLMProvider
from .media_config import MediaConfig
from .web_scraper import WebScraper

# Configuration du logger
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class IA:
    """
    Classe principale pour les interactions avec les LLMs
    Supporte OpenAI provider
    """
    
    def __init__(self, config_path: Optional[str] = None, provider_type: Optional[str] = None,
                 prompt_repetition: bool = False):
        """
        Initialise la classe IA avec la configuration
        
        Args:
            config_path: Chemin vers le fichier de configuration JSON
            provider_type: Type de provider ('openai')
                          Si None, utilise celui spécifié dans config ou 'openai' par défaut
            prompt_repetition: If True, repeat the rendered prompt before
                sending it to the LLM.  This allows each token in the
                prompt to attend to every other token in a causal LM
                (see "Prompt Repetition" technique).
        """
        self.prompt_repetition = prompt_repetition
        self.config = ConfigManager(config_path)
        self._config_dir = Path(self.config.config_path).resolve().parent
        
        # Détermine le provider à utiliser
        if provider_type is None:
            provider_type = self.config.get_default_provider_type()
        
        logger.info(f"Initializing IA with provider: {provider_type}")
        
        # Récupère la config du provider
        provider_config = self.config.get_provider_config(provider_type)
        
        # Initialise le provider
        try:
            self.provider: BaseLLMProvider = get_provider(provider_type, provider_config)
            if not self.provider.is_available():
                logger.warning(f"Provider {provider_type} is not available, falling back to OpenAI")
                provider_config = self.config.get_provider_config("openai")
                self.provider = get_provider("openai", provider_config)
        except Exception as e:
            logger.error(f"Failed to initialize provider {provider_type}: {e}")
            logger.info("Falling back to OpenAI provider")
            provider_config = self.config.get_provider_config("openai")
            self.provider = get_provider("openai", provider_config)
        
        # Get max word limit from provider config
        self.ai_max_nb_word = provider_config.get("max_nb_word", 4000)
        self.timeout = provider_config.get("timeout", {})
        
        scraper_path = self._config_dir / "configScraper.json"
        if scraper_path.exists():
            with open(scraper_path, "r", encoding="utf-8") as sf:
                sd = json.load(sf)
            scraper_config = {
                "use_playwright": sd.get("usePlaywright", sd.get("use_playwright", True)),
                "timeout": sd.get("timeout", 30),
                "excluded_domains": sd.get(
                    "excludedDomains", sd.get("excluded_domains", [])
                ),
            }
            media_from_file = MediaConfig.from_config_file(str(scraper_path))
        else:
            scraper_config = self.config.config.get("scraper", {})
            media_from_file = MediaConfig.from_config_file(
                str(self._config_dir / "config.json")
            )
        self.web_scraper = WebScraper(
            use_playwright=scraper_config.get("use_playwright", True),
            timeout=scraper_config.get("timeout", 30),
            excluded_domains=scraper_config.get("excluded_domains", []),
            media_config=media_from_file,
        )
        
        # Lazy-loaded scenarios data (for classification prompts)
        self._scenarios_data = None
        self._category_index = None
    
    def _load_scenarios(self):
        """
        Lazy-load the scenarios JSON used by classification templates.
        Searches for scenarios_llm_optimized.json or scenarios.json.
        """
        if self._scenarios_data is not None:
            return
        
        from pathlib import Path
        # In this Flask project, core/ sits directly under the project root (ponamtky),
        # so the workspace root is one level up from this file.
        workspace_root = Path(__file__).resolve().parent.parent
        path = workspace_root / "config" / "scenarios" / "scenarios_llm_optimized.json"
        if not path.exists():
            path = workspace_root / "config" / "scenarios.json"
        
        if path.exists():
            with open(path, 'r', encoding='utf-8') as f:
                self._scenarios_data = json.load(f)
        else:
            logger.warning(f"Scenarios file not found at {path}")
            self._scenarios_data = {"categories": []}
        
        self._category_index = {
            cat["categoryCode"]: cat
            for cat in self._scenarios_data.get("categories", [])
        }
    
    def _get_category_definitions(self) -> str:
        """Build the category definitions string for classification prompts."""
        self._load_scenarios()
        definitions = []
        for cat in self._scenarios_data.get("categories", []):
            definitions.append(
                f"- {cat['categoryCode']}: {cat['categoryName']}\n"
                f"  {cat['categoryDescription']}"
            )
        return "\n\n".join(definitions)
    
    def _get_scenario_definitions(self, category_code: str) -> str:
        """Build the scenario definitions string for a given category."""
        self._load_scenarios()
        category = self._category_index.get(category_code)
        if not category:
            return ""
        
        definitions = []
        for s in category.get("scenarios", []):
            text = f"**{s['scenarioCode']}**: {s['scenarioName']}\n"
            text += f"Definition: {s.get('shortDefinition', s.get('scenarioDescription', ''))}\n"
            if s.get("keySignals"):
                text += f"Key signals: {', '.join(s['keySignals'])}\n"
            if s.get("typicalExample"):
                text += f"Example: {s['typicalExample']}\n"
            if s.get("exclusions"):
                text += f"NOT this scenario if: {'; '.join(s['exclusions'])}"
            definitions.append(text)
        return "\n\n".join(definitions)
    
    @staticmethod
    def clean_ai_input(text: str) -> str:
        """
        Nettoie le texte pour l'API en retirant les caractères non-ASCII
        
        Args:
            text: Texte à nettoyer
            
        Returns:
            Texte nettoyé contenant uniquement des caractères ASCII imprimables
        """
        try:
            # Remplace les espaces multiples par un seul espace
            clean_text = re.sub(r'\s+', ' ', text).strip()
            
            # Retire les tirets suivis d'espaces
            clean_text = re.sub(r'-\s+', '', clean_text)
            
            # Remplace les espaces insécables
            clean_text = clean_text.replace('\u00A0', ' ')
            
            # Retire les caractères non-ASCII
            clean_text = re.sub(r'[^\x00-\x7F]', '', clean_text)
            
            # Normalise les caractères spéciaux
            clean_text = unicodedata.normalize('NFKC', clean_text)
            
            return clean_text
        except Exception as e:
            logger.error(f"Error cleaning AI input: {e}")
            raise
    
    def _get_ai_response_completion(
        self, 
        prompt: str, 
        assistant_behavior: str, 
        temperature: float
    ) -> Optional[str]:
        """
        Envoie une requête au LLM et récupère la réponse
        Utilise le provider configuré (OpenAI, Ollama, etc.)
        
        Args:
            prompt: Le prompt à envoyer
            assistant_behavior: Le comportement de l'assistant (role)
            temperature: Paramètre de température (0-1)
            
        Returns:
            La réponse de l'assistant ou None en cas d'erreur
        """
        try:
            # Nettoie le prompt
            prompt = self.clean_ai_input(prompt)
            
            logger.debug(f"Provider: {self.provider.provider_name}")
            logger.debug(f"Prompt: {prompt[:200]}...")
            
            # Utilise le provider pour générer la réponse
            response = self.provider.complete(
                prompt=prompt,
                system_message=assistant_behavior,
                temperature=temperature
            )
            
            return response
            
        except Exception as e:
            logger.error(f"Error during completion: {e}")
            return None
    
    def _process_request_completion(
        self,
        text: str,
        intro_prompt: str,
        assistant_behavior: str,
        temperature: float,
        one_chunk_at_most: bool = False
    ) -> Optional[str]:
        """
        Traite une requête en découpant le texte en chunks si nécessaire
        
        Args:
            text: Texte à traiter
            intro_prompt: Prompt d'introduction
            assistant_behavior: Comportement de l'assistant
            temperature: Température
            one_chunk_at_most: Si True, traite uniquement le premier chunk
            
        Returns:
            Réponse agrégée ou None
        """
        try:
            # Découpe le texte en chunks
            chunks = chunk_text_by_words(text, self.ai_max_nb_word)
            logger.debug(f"Number of chunks: {len(chunks)}")
            
            # Traite chaque chunk
            chunk_responses = []
            nb_processed_chunks = 0
            
            for chunk in chunks:
                chunk_response = self._get_ai_response_completion(
                    f"{intro_prompt}\n{chunk}",
                    assistant_behavior,
                    temperature
                )
                
                if not is_empty(chunk_response):
                    chunk_responses.append(chunk_response)
                    nb_processed_chunks += 1
                    
                if one_chunk_at_most and nb_processed_chunks > 0:
                    break
            
            # Agrège les réponses
            if nb_processed_chunks == 0:
                return None
            elif nb_processed_chunks == 1:
                response = chunk_responses[0].strip()
            else:
                # Si plusieurs chunks, on résume les réponses
                concat_responses = " ".join(chunk_responses)
                trimmed = trim_to_word_limit(concat_responses, self.ai_max_nb_word)
                response = self._get_ai_response_completion(
                    trimmed,
                    assistant_behavior,
                    temperature
                )
            
            # Nettoie la réponse
            if response:
                response = self._remove_surrounding_quotes(response)
                
            return response
            
        except Exception as e:
            logger.error(f"Error processing completion request: {e}")
            return None
    
    def _get_ai_response_embedding(self, text: str) -> Optional[List[float]]:
        """
        Génère un embedding pour le texte donné
        Utilise le provider configuré
        
        Args:
            text: Texte à embedder
            
        Returns:
            Liste de floats représentant l'embedding ou None
        """
        try:
            # Nettoie le texte
            text = self.clean_ai_input(text)
            
            logger.debug(f"Generating embedding with {self.provider.provider_name}")
            
            # Utilise le provider pour générer l'embedding
            if not self.provider.supports_embeddings():
                logger.warning(f"Provider {self.provider.provider_name} doesn't support embeddings")
                return None
            
            embedding = self.provider.embed(text)
            return embedding
            
        except Exception as e:
            logger.error(f"Error during embedding: {e}")
            return None
    
    def _process_request_embedding(
        self,
        text: str,
        one_chunk_at_most: bool = True
    ) -> Optional[List[float]]:
        """
        Traite une requête d'embedding en gérant les chunks
        
        Args:
            text: Texte à embedder
            one_chunk_at_most: Si True, utilise seulement le premier chunk
            
        Returns:
            Embedding moyen ou None
        """
        try:
            # Découpe en chunks
            chunks = chunk_text_by_words(text, self.ai_max_nb_word)
            logger.info(f"Number of chunks: {len(chunks)}")
            
            embeddings = []
            nb_processed_chunks = 0
            
            for chunk in chunks:
                chunk_embedding = self._get_ai_response_embedding(chunk)
                
                if chunk_embedding:
                    embeddings.append(chunk_embedding)
                    nb_processed_chunks += 1
                    
                if one_chunk_at_most and nb_processed_chunks > 0:
                    break
            
            if not embeddings:
                return None
            
            # Calcule la moyenne si plusieurs embeddings
            if len(embeddings) == 1:
                return embeddings[0]
            else:
                # Moyenne des embeddings
                avg_embedding = [
                    sum(emb[i] for emb in embeddings) / len(embeddings)
                    for i in range(len(embeddings[0]))
                ]
                return avg_embedding
                
        except Exception as e:
            logger.error(f"Error processing embedding request: {e}")
            return None
    
    @staticmethod
    def _remove_surrounding_quotes(text: str) -> str:
        """Retire les guillemets entourant le texte"""
        text = text.strip()
        if text.startswith('"') and text.endswith('"') and len(text) >= 2:
            return text[1:-1]
        elif text.startswith('"'):
            return text[1:]
        elif text.endswith('"'):
            return text[:-1]
        return text
    
    @staticmethod
    def _clean_response(response: Optional[str]) -> Optional[str]:
        """Nettoie la réponse en retirant les espaces avant les sauts de ligne"""
        if not response:
            return response
        return re.sub(r'[ \t]+(?=\n)', '', response)
    
    # === MÉTHODES INTERNES D'APPEL À L'IA ===
    # Correspondent aux méthodes statiques de la classe Java IA.java
    
    def _summarize_text(self, text: str) -> Optional[str]:
        """
        Génère un résumé du texte via l'IA.
        Équivalent interne de Java: IA.summarize(strText)
        """
        logger.debug("Request: _summarize_text")
        usage_config = self.config.get_usage_config("summary")
        prompt_template = self.config.get_prompt("summary", text="")
        
        response = self._process_request_completion(
            text,
            prompt_template,
            usage_config["assistant_role"],
            usage_config["temperature"],
            one_chunk_at_most=False
        )
        return self._clean_response(response)
    
    def _title_text(self, text: str) -> Optional[str]:
        """
        Génère un titre pour le texte via l'IA.
        Équivalent interne de Java: IA.title(strText)
        """
        logger.debug("Request: _title_text")
        usage_config = self.config.get_usage_config("title")
        prompt_template = self.config.get_prompt("title", text="")
        
        response = self._process_request_completion(
            text,
            prompt_template,
            usage_config["assistant_role"],
            usage_config["temperature"],
            one_chunk_at_most=False
        )
        return self._clean_response(response)
    
    def _classify_text(self, text: str, classifier_name: str, **kwargs) -> Optional[str]:
        """
        Classifie le texte via l'IA.
        Équivalent interne de Java: IA.classify(strClassif, strText)
        
        Auto-populates template variables (category_definitions, scenario_definitions)
        from the scenarios config if not explicitly provided.
        Supports both Jinja2 templates and legacy inline "prompt" format.
        """
        logger.debug(f"Request: _classify_text with {classifier_name}")
        
        try:
            usage_config = self.config.get_classification_config(classifier_name)
            
            # Auto-populate template variables that the Jinja2 templates expect
            if classifier_name == "category" and "category_definitions" not in kwargs:
                kwargs["category_definitions"] = self._get_category_definitions()
            elif classifier_name == "scenario":
                category = kwargs.get("category", kwargs.get("category_code", ""))
                if "scenario_definitions" not in kwargs and category:
                    kwargs["scenario_definitions"] = self._get_scenario_definitions(category)
                if "category_name" not in kwargs and category:
                    self._load_scenarios()
                    cat_data = self._category_index.get(category, {})
                    kwargs["category_name"] = cat_data.get("categoryName", category)
            
            # Build the prompt using the config manager which handles
            # both Jinja2 templates and legacy {{VAR}} format
            prompt = self.config.get_classification_prompt(
                classifier_name, text=text, **kwargs
            )
            
            # Prompt repetition: duplicate the rendered prompt so every
            # token can attend to every other token in a causal LM.
            if self.prompt_repetition:
                prompt = prompt + "\n\n" + prompt
                logger.debug("Prompt repetition applied (length doubled)")
            
            # The Jinja2 template already includes the text, so we call
            # _get_ai_response_completion directly (no chunking/appending)
            response = self._get_ai_response_completion(
                prompt,
                usage_config["assistant_role"],
                usage_config["temperature"],
            )
            return self._clean_response(response)
                
        except Exception as e:
            logger.error(f"Error during classification: {e}")
            return None
    
    # === MÉTHODES PUBLIQUES (Interface WSContent) ===
    # Reproduisent les services du webservice Java WSContent
    
    def load(self, url: str, force_playwright: bool = False) -> Dict[str, Any]:
        """
        Charge et extrait le contenu d'une URL.
        Équivalent de WSContent.load(url)
        
        Args:
            url: URL à charger
            force_playwright: Force l'utilisation de Playwright
            
        Returns:
            Dict avec 'success', 'text', 'error', 'url', 'is_pdf', 'method', 'text_length'
        """
        logger.info(f"Loading content from URL: {url}")
        
        text, metadata = self.web_scraper.load(url, force_playwright=force_playwright)
        result = metadata.copy()
        result['text'] = text
        
        if result['success']:
            logger.info(f"Successfully loaded {result['text_length']} chars from {url}")
        else:
            logger.error(f"Failed to load {url}: {result['error']}")
        
        return result
    
    def summarize(self, url: str, force: bool = False, force_playwright: bool = False) -> Dict[str, Any]:
        """
        Charge une URL, résume le contenu et génère un titre.
        Équivalent de WSContent.summarize(url)
        
        En Java, cette méthode lit le texte archivé en base, le résume via IA.summarize(),
        puis génère un titre via IA.title(summary). Ici, sans base de données,
        on charge directement l'URL puis on applique le même traitement.
        
        Args:
            url: URL à charger et résumer
            force: Force le recalcul même si déjà effectué (compatibilité Java)
            force_playwright: Force l'utilisation de Playwright pour le chargement
            
        Returns:
            Dict contenant:
            {
                'success': bool,
                'title': Optional[str],
                'summary': Optional[str],
                'url': str,
                'error': Optional[str]
            }
        """
        logger.info(f"Request: summarize URL {url}")
        
        # Étape 1: Charger le contenu de l'URL
        load_result = self.load(url, force_playwright=force_playwright)
        
        if not load_result['success']:
            return {
                'success': False,
                'title': None,
                'summary': None,
                'url': url,
                'error': load_result['error']
            }
        
        text = load_result['text']
        
        # Étape 2: Résumer le texte (IA.summarize)
        summary = self._summarize_text(text)
        if is_empty(summary):
            return {
                'success': False,
                'title': None,
                'summary': None,
                'url': url,
                'error': 'ERR_SUMMARIZING'
            }
        
        # Étape 3: Générer un titre à partir du résumé (IA.title)
        title = self._title_text(summary)
        if is_empty(title):
            title = ""
        
        return {
            'success': True,
            'title': title,
            'summary': summary,
            'url': url,
            'error': None
        }
    
    def summarizeLite(self, text: str) -> Dict[str, Any]:
        """
        Résume un texte directement et génère un titre, sans charger d'URL.
        Équivalent de WSContent.summarizeLite(text)
        
        Args:
            text: Texte à résumer
            
        Returns:
            Dict contenant:
            {
                'success': bool,
                'title': Optional[str],
                'summary': Optional[str],
                'error': Optional[str]
            }
        """
        logger.info("Request: summarizeLite")
        
        if is_empty(text):
            return {
                'success': False,
                'title': None,
                'summary': None,
                'error': 'ERR_TXT_EMPTY'
            }
        
        # Résumer le texte (IA.summarize)
        summary = self._summarize_text(text)
        if is_empty(summary):
            return {
                'success': False,
                'title': None,
                'summary': None,
                'error': 'ERR_SUMMARIZING'
            }
        
        # Générer un titre à partir du résumé (IA.title)
        title = self._title_text(summary)
        if is_empty(title):
            title = ""
        
        return {
            'success': True,
            'title': title,
            'summary': summary,
            'error': None
        }
    
    def classify(self, url: str, classifier_name: str = "scenario",
                 classify_text: bool = False, force: bool = False,
                 force_playwright: bool = False, **kwargs) -> Dict[str, Any]:
        """
        Charge une URL, résume le contenu, puis classifie le résumé (ou le texte brut).
        Équivalent de WSContent.classify(url, classif, classifyText)
        
        En Java, la classification est par défaut effectuée sur le résumé
        (pour réduire les coûts et simplifier la tâche de l'IA).
        Si classify_text=True, la classification est effectuée sur le texte brut.
        
        Args:
            url: URL à charger et classifier
            classifier_name: Nom du classifieur (ex: "scenario")
            classify_text: Si True, classifie le texte brut ; si False, classifie le résumé
            force: Force le recalcul
            force_playwright: Force l'utilisation de Playwright
            **kwargs: Arguments additionnels pour le prompt
            
        Returns:
            Dict contenant:
            {
                'success': bool,
                'category': Optional[str],
                'url': str,
                'error': Optional[str]
            }
        """
        logger.info(f"Request: classify URL {url} with {classifier_name}")
        
        # Étape 1: Charger le contenu de l'URL
        load_result = self.load(url, force_playwright=force_playwright)
        
        if not load_result['success']:
            return {
                'success': False,
                'category': None,
                'url': url,
                'error': load_result['error']
            }
        
        text = load_result['text']
        
        # Étape 2: Déterminer le texte à classifier
        if classify_text:
            # Classifie le texte brut
            text_to_classify = text
        else:
            # Classifie le résumé (comportement par défaut, comme en Java)
            summary = self._summarize_text(text)
            if is_empty(summary):
                return {
                    'success': False,
                    'category': None,
                    'url': url,
                    'error': 'ERR_SUMMARY_NOTDEFINED'
                }
            text_to_classify = summary
        
        # Étape 3: Classifier (with two-level auto-handling)
        result = self.classifyLite(text_to_classify, classifier_name, **kwargs)
        result['url'] = url
        return result
    
    @staticmethod
    def _parse_classification_response(response: Optional[str]) -> Optional[dict]:
        """
        Parse a JSON classification response from the LLM.
        Handles markdown code-fence wrappers (```json ... ```).
        Returns parsed dict or None.
        """
        if not response:
            return None
        response = response.strip()
        if response.startswith("```json"):
            response = response[7:]
        if response.startswith("```"):
            response = response[3:]
        if response.endswith("```"):
            response = response[:-3]
        response = response.strip()
        try:
            return json.loads(response)
        except json.JSONDecodeError as e:
            logger.warning(f"Failed to parse classification JSON: {e}")
            logger.debug(f"Raw response: {response[:500]}")
            return None
    
    def classifyLite(self, text: str, classifier_name: str = "scenario", **kwargs) -> Dict[str, Any]:
        """
        Classifie un texte directement, sans charger d'URL.
        Équivalent de WSContent.classifyLite(classif, text)
        
        When classifier_name="scenario" (default) and no 'category' kwarg is
        provided, performs two-level classification: first category, then
        scenario within that category.  This mirrors the Java TwoLevelClassifier
        behaviour and means a single call produces the full result.
        
        Args:
            text: Texte à classifier
            classifier_name: Nom du classifieur ("category", "scenario")
            **kwargs: Arguments additionnels pour le prompt (e.g. category="CONDUCT")
            
        Returns:
            Dict contenant:
            {
                'success': bool,
                'category': Optional[dict or str],  # parsed JSON if possible
                'error': Optional[str]
            }
        """
        logger.info(f"Request: classifyLite with {classifier_name}")
        
        if is_empty(text):
            return {
                'success': False,
                'category': None,
                'error': 'ERR_TXT_EMPTY'
            }
        
        # Two-level flow: if asking for scenario without a category, classify category first
        if classifier_name == "scenario" and not kwargs.get("category") and not kwargs.get("category_code"):
            logger.info("Two-level classification: step 1 — category")
            cat_raw = self._classify_text(text, "category", **kwargs)
            cat_parsed = self._parse_classification_response(cat_raw)
            
            if not cat_parsed or not cat_parsed.get("categoryCode"):
                return {
                    'success': False,
                    'category': cat_parsed or cat_raw,
                    'error': 'ERR_CATEGORY_CLASSIFICATION'
                }
            
            category_code = cat_parsed["categoryCode"]

            # Short-circuit: skip scenario classification when content is not relevant
            if category_code == "NOT_RELEVANT":
                logger.info("Category is NOT_RELEVANT — skipping scenario classification")
                return {
                    'success': True,
                    'category': cat_parsed,
                    'error': None
                }

            logger.info(f"Two-level classification: step 2 — scenario in {category_code}")
            
            scen_raw = self._classify_text(
                text, "scenario", category=category_code, **kwargs
            )
            scen_parsed = self._parse_classification_response(scen_raw)
            
            if not scen_parsed:
                return {
                    'success': False,
                    'category': cat_parsed,
                    'error': 'ERR_SCENARIO_CLASSIFICATION'
                }
            
            # Merge both levels into a single result
            return {
                'success': True,
                'category': {**cat_parsed, 'scenario': scen_parsed},
                'error': None
            }
        
        # Single-level classification (category-only, or scenario with explicit category)
        raw_response = self._classify_text(text, classifier_name, **kwargs)
        if is_empty(raw_response):
            return {
                'success': False,
                'category': None,
                'error': 'ERR_CLASSIFYING'
            }
        
        parsed = self._parse_classification_response(raw_response)
        return {
            'success': True,
            'category': parsed if parsed else raw_response,
            'error': None
        }
    
    def title(self, text: str) -> Optional[str]:
        """
        Génère un titre pour le texte.
        Équivalent de Java: IA.title(strText)
        
        Args:
            text: Texte pour lequel générer un titre
            
        Returns:
            Titre généré
        """
        return self._title_text(text)
    
    def embedding(self, text: str) -> Optional[List[float]]:
        """
        Génère un embedding pour le texte.
        Équivalent de Java: IA.embedding(strText)
        
        Args:
            text: Texte à embedder
            
        Returns:
            Liste de floats représentant l'embedding
        """
        return self._process_request_embedding(text, one_chunk_at_most=True)

    def resolve_document_text(
        self,
        read: int,
        url: Optional[str],
        text: Optional[str],
        upload_file_path: Optional[str] = None,
        upload_filename: Optional[str] = None,
        force_playwright: bool = False,
    ) -> Tuple[Optional[str], Optional[str]]:
        """Returns (document_text, error_code) for news-classifier API (read 1/2/3)."""
        if read == 3:
            return self._resolve_uploaded_text(upload_file_path, upload_filename)
        if read == 1:
            if not url or not isinstance(url, str):
                return None, "MISSING_URL"
            load_result = self.load(url, force_playwright=force_playwright)
            if not load_result.get("success"):
                return None, load_result.get("error") or "LOAD_FAILED"
            return load_result.get("text"), None
        if read == 2:
            if not text or not isinstance(text, str) or not str(text).strip():
                return None, "MISSING_TEXT"
            return text, None
        return None, "INVALID_READ"

    def _resolve_uploaded_text(
        self, upload_file_path: Optional[str], upload_filename: Optional[str]
    ) -> Tuple[Optional[str], Optional[str]]:
        if not upload_file_path:
            return None, "MISSING_UPLOAD_FILE"

        path = Path(upload_file_path)
        if not path.exists() or not path.is_file():
            return None, "UPLOAD_FILE_NOT_FOUND"

        suffix = (path.suffix or "").lower()
        if upload_filename:
            suffix = (Path(upload_filename).suffix or suffix).lower()

        if suffix not in {".txt", ".pdf"}:
            return None, "UNSUPPORTED_UPLOAD_FILE_TYPE"

        if suffix == ".txt":
            try:
                text = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                text = path.read_text(encoding="latin-1")
            except Exception:
                return None, "UPLOAD_TEXT_READ_FAILED"
            if not text or not text.strip():
                return None, "UPLOAD_EMPTY_TEXT"
            return text, None

        # PDF path
        try:
            from .web_scraper import PDFExtractor

            text = PDFExtractor.extract_text_from_pdf(str(path))
            if not text or not text.strip():
                return None, "UPLOAD_PDF_NO_TEXT"
            return text, None
        except Exception:
            return None, "UPLOAD_PDF_READ_FAILED"

    def summarize_news_spec(
        self,
        read: int,
        url: Optional[str] = None,
        text: Optional[str] = None,
        upload_file_path: Optional[str] = None,
        upload_filename: Optional[str] = None,
        force_playwright: bool = False,
    ) -> Dict[str, Any]:
        """SOW summarize response: returnStatus, title, summary, optional errorMessage."""
        doc, err = self.resolve_document_text(
            read,
            url,
            text,
            upload_file_path=upload_file_path,
            upload_filename=upload_filename,
            force_playwright=force_playwright,
        )
        if err:
            return {
                "returnStatus": 1,
                "title": None,
                "summary": None,
                "errorMessage": err,
            }
        summary = self._summarize_text(doc)
        if is_empty(summary):
            return {
                "returnStatus": 4,
                "title": None,
                "summary": None,
                "errorMessage": "ERR_SUMMARIZING",
            }
        title = self._title_text(summary) or ""
        return {"returnStatus": 0, "title": title, "summary": summary}

    def classify_news_spec(
        self,
        read: int,
        policy: Policy,
        url: Optional[str] = None,
        text: Optional[str] = None,
        category: Optional[str] = None,
        upload_file_path: Optional[str] = None,
        upload_filename: Optional[str] = None,
        force_playwright: bool = False,
    ) -> Dict[str, Any]:
        """SOW classify response: returnStatus, category, scenario, optional errorMessage."""
        try:
            policy = policy if isinstance(policy, Policy) else Policy(int(policy))
        except (TypeError, ValueError):
            return {
                "returnStatus": 1,
                "category": None,
                "scenario": None,
                "errorMessage": "INVALID_POLICY",
            }

        doc, err = self.resolve_document_text(
            read,
            url,
            text,
            upload_file_path=upload_file_path,
            upload_filename=upload_filename,
            force_playwright=force_playwright,
        )
        if err:
            return {
                "returnStatus": 1,
                "category": None,
                "scenario": None,
                "errorMessage": err,
            }
        summary = self._summarize_text(doc)
        if is_empty(summary):
            return {
                "returnStatus": 4,
                "category": None,
                "scenario": None,
                "errorMessage": "ERR_SUMMARIZING",
            }
        text_to_classify = summary

        if policy == Policy.CATEGORY_ONLY:
            raw = self._classify_text(text_to_classify, "category")
            parsed = self._parse_classification_response(raw)
            code = (parsed or {}).get("categoryCode") if parsed else None
            return {"returnStatus": 0, "category": code}

        if policy == Policy.SCENARIO_ONLY:
            if not category or not isinstance(category, str):
                return {
                    "returnStatus": 1,
                    "category": None,
                    "scenario": None,
                    "errorMessage": "MISSING_CATEGORY",
                }
            raw = self._classify_text(
                text_to_classify, "scenario", category=category
            )
            parsed = self._parse_classification_response(raw)
            scen = (parsed or {}).get("scenarioCode") if parsed else None
            return {"returnStatus": 0, "category": category, "scenario": scen}

        if policy == Policy.CATEGORY_AND_SCENARIO:
            r = self.classifyLite(text_to_classify, "scenario")
            if not r.get("success"):
                return {
                    "returnStatus": 5,
                    "category": None,
                    "scenario": None,
                    "errorMessage": r.get("error") or "ERR_CLASSIFYING",
                }
            cat = r.get("category")
            if not isinstance(cat, dict):
                return {"returnStatus": 0, "category": None, "scenario": None}
            ccode = cat.get("categoryCode")
            if ccode == "NOT_RELEVANT":
                return {"returnStatus": 0, "category": "NOT_RELEVANT", "scenario": None}
            scen_obj = cat.get("scenario")
            scode = (
                scen_obj.get("scenarioCode")
                if isinstance(scen_obj, dict)
                else None
            )
            return {"returnStatus": 0, "category": ccode, "scenario": scode}

        return {
            "returnStatus": 1,
            "category": None,
            "scenario": None,
            "errorMessage": "INVALID_POLICY",
        }
