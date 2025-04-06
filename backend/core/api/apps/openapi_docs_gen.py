import json
import argparse
from typing import Dict, Any, List, Set, Union
import os

def extract_unique_structure(data: Any, path: str = "", unique_fields: Dict[str, Dict] = None) -> Dict[str, Dict]:
    """
    Extrahiert die eindeutige Struktur einer verschachtelten JSON.
    
    Args:
        data: Das JSON-Objekt
        path: Der aktuelle Pfad in der JSON-Struktur
        unique_fields: Dictionary mit eindeutigen Feldern
        
    Returns:
        Dictionary mit eindeutigen Feldern und deren Typ/Beispielwert
    """
    if unique_fields is None:
        unique_fields = {}
    
    if isinstance(data, dict):
        for key, value in data.items():
            current_path = f"{path}.{key}" if path else key
            field_type = type(value).__name__
            
            if current_path not in unique_fields:
                example = None
                if not isinstance(value, (dict, list)):
                    example = value
                
                unique_fields[current_path] = {
                    "type": field_type,
                    "example": example
                }
            
            extract_unique_structure(value, current_path, unique_fields)
            
    elif isinstance(data, list) and data:
        # Bei Listen nehmen wir nur das erste Element für die Struktur
        sample_item = data[0]
        current_path = f"{path}[]"
        
        field_type = type(sample_item).__name__
        example = None
        if not isinstance(sample_item, (dict, list)) and sample_item is not None:
            example = sample_item
            
        if current_path not in unique_fields:
            unique_fields[current_path] = {
                "type": field_type,
                "example": example
            }
            
        extract_unique_structure(sample_item, current_path, unique_fields)
        
    return unique_fields

def generate_openapi_schema(unique_fields: Dict[str, Dict]) -> Dict:
    """
    Generiert ein OpenAPI-ähnliches Schema aus den eindeutigen Feldern.
    
    Args:
        unique_fields: Dictionary mit eindeutigen Feldern
        
    Returns:
        OpenAPI-ähnliches Schema
    """
    schema = {
        "openapi": "3.0.0",
        "info": {
            "title": "API Dokumentation",
            "description": "Automatisch generierte API-Dokumentation",
            "version": "1.0.0"
        },
        "components": {
            "schemas": {
                "MainObject": {
                    "type": "object",
                    "properties": {}
                }
            }
        }
    }
    
    properties = schema["components"]["schemas"]["MainObject"]["properties"]
    
    for path, info in unique_fields.items():
        field_type = info["type"]
        example = info["example"]
        
        path_parts = path.split(".")
        current_dict = properties
        
        # Navigiere durch die verschachtelte Struktur
        for i, part in enumerate(path_parts[:-1]):
            if "[]" in part:
                base_part = part.replace("[]", "")
                
                if base_part not in current_dict:
                    # Prüfen, ob der nächste Teil ein Primitive oder ein Objekt ist
                    is_primitive = False
                    if i + 1 < len(path_parts) - 1:
                        next_part = path_parts[i + 1]
                        if "[]" in next_part:
                            # Eine Liste von Listen
                            is_primitive = True
                    
                    if is_primitive:
                        current_dict[base_part] = {
                            "type": "array",
                            "items": {
                                "type": "array",
                                "items": {
                                    "type": "string"  # Standard, wird später ersetzt
                                }
                            }
                        }
                    else:
                        current_dict[base_part] = {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {}
                            }
                        }
                
                # Nur versuchen auf properties zuzugreifen, wenn items vom Typ object ist
                if "items" in current_dict[base_part] and current_dict[base_part]["items"]["type"] == "object":
                    current_dict = current_dict[base_part]["items"]["properties"]
                else:
                    # Wenn wir hier sind, haben wir ein Array von Primitiven
                    # Wir können nicht weiter navigieren, also brechen wir die Schleife ab
                    break
            else:
                if part not in current_dict:
                    current_dict[part] = {
                        "type": "object",
                        "properties": {}
                    }
                
                current_dict = current_dict[part]["properties"]
        
        # Wenn wir vorzeitig aus der Schleife gebrochen sind, überspringen wir das Setzen des letzten Elements
        if "[]" in path_parts[-2] and len(path_parts) > 1:
            if current_dict != properties:  # Nur überspringen, wenn wir tatsächlich gebrochen haben
                continue
        
        # Setze das letzte Element
        last_part = path_parts[-1]
        if "[]" in last_part:
            base_part = last_part.replace("[]", "")
            
            if field_type == "dict":
                current_dict[base_part] = {
                    "type": "array",
                    "items": {
                        "type": "object"
                    }
                }
            else:
                current_dict[base_part] = {
                    "type": "array",
                    "items": {
                        "type": map_python_to_openapi_type(field_type)
                    }
                }
                
                if example is not None:
                    current_dict[base_part]["example"] = [example]
        else:
            if field_type == "dict":
                current_dict[last_part] = {
                    "type": "object"
                }
            else:
                current_dict[last_part] = {
                    "type": map_python_to_openapi_type(field_type)
                }
                
                if example is not None:
                    current_dict[last_part]["example"] = example
    
    return schema

def map_python_to_openapi_type(python_type: str) -> str:
    """
    Wandelt Python-Datentypen in OpenAPI-Datentypen um.
    
    Args:
        python_type: Python-Datentyp
        
    Returns:
        Entsprechender OpenAPI-Datentyp
    """
    type_mapping = {
        "str": "string",
        "int": "integer",
        "float": "number",
        "bool": "boolean",
        "list": "array",
        "dict": "object",
        "NoneType": "null"
    }
    
    return type_mapping.get(python_type, "string")

def main():
    parser = argparse.ArgumentParser(description="Wandelt eine JSON-Datei in eine lesbarere Form um")
    parser.add_argument("input_file", help="Pfad zur JSON-Eingabedatei")
    parser.add_argument("--output-dir", default="output", help="Ausgabe-Verzeichnis")
    
    args = parser.parse_args()
    
    try:
        with open(args.input_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except Exception as e:
        print(f"Fehler beim Lesen der JSON-Datei: {e}")
        return
    
    # Eindeutige Struktur extrahieren
    unique_fields = extract_unique_structure(data)
    
    # OpenAPI-Schema generieren
    try:
        openapi_schema = generate_openapi_schema(unique_fields)
    except Exception as e:
        print(f"Fehler beim Generieren des OpenAPI-Schemas: {e}")
        # Als Fallback nur die eindeutige Struktur speichern
        os.makedirs(args.output_dir, exist_ok=True)
        with open(os.path.join(args.output_dir, "unique_structure.json"), 'w', encoding='utf-8') as f:
            json.dump(unique_fields, f, indent=2, ensure_ascii=False)
        print(f"Eindeutige Struktur wurde in {args.output_dir}/unique_structure.json gespeichert.")
        return
    
    # Ausgabeverzeichnis erstellen, falls es nicht existiert
    os.makedirs(args.output_dir, exist_ok=True)
    
    # Ergebnisse speichern
    with open(os.path.join(args.output_dir, "unique_structure.json"), 'w', encoding='utf-8') as f:
        json.dump(unique_fields, f, indent=2, ensure_ascii=False)
    
    with open(os.path.join(args.output_dir, "openapi_schema.json"), 'w', encoding='utf-8') as f:
        json.dump(openapi_schema, f, indent=2, ensure_ascii=False)
    
    print(f"Eindeutige Struktur wurde in {args.output_dir}/unique_structure.json gespeichert.")
    print(f"OpenAPI-Schema wurde in {args.output_dir}/openapi_schema.json gespeichert.")

if __name__ == "__main__":
    main()