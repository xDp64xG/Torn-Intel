"""
modules/armoury/parser.py

Parse armoury news events from Torn API into structured data.
"""

import re
from html import unescape


class ArmouryParser:
    """Parse HTML-formatted armoury news into structured events"""

    # Torn API item type -> local reporting category.
    TYPE_TO_CATEGORY = {
        "drug": "Drug",
        "medical": "Medical",
        "temporary": "Temporary",
        "defensive": "Armor",
        "melee": "Weapon",
        "primary": "Weapon",
        "secondary": "Weapon",
        "tool": "Utility",
        "material": "Utility",
        "enhancer": "Utility",
        "booster": "Booster",
        "alcohol": "Consumable",
        "candy": "Consumable",
        "energy drink": "Consumable",
        "food": "Consumable",
    }
    
    # Event type patterns
    PATTERNS = {
        "loaned_to_player": re.compile(
            r'profiles\.php\?XID=(\d+)">([^<]+)</a>\s+loaned\s+([\d,]+)x\s+([^<]+?)\s+to\s+<a[^>]*profiles\.php\?XID=(\d+)">([^<]+)</a>\s+from the faction armory',
            re.IGNORECASE
        ),
        "used_faction_item": re.compile(
            r'profiles\.php\?XID=(\d+)">([^<]+)</a> used one of the faction\'s ([^<]+?) items',
            re.IGNORECASE
        ),
        "filled_blood_bag": re.compile(
            r'profiles\.php\?XID=(\d+)">([^<]+)</a> filled one of the faction\'s Empty Blood Bags',
            re.IGNORECASE
        ),
        "deposited": re.compile(
            r'profiles\.php\?XID=(\d+)">([^<]+)</a> deposited ([\d,]+)x ([^<]+)',
            re.IGNORECASE
        ),
        "sent_item": re.compile(
            r'profiles\.php\?XID=(\d+)">([^<]+)</a> was sent ([\d,]+)x ([^<]+)',
            re.IGNORECASE
        ),
        "received_item": re.compile(
            r'profiles\.php\?XID=(\d+)">([^<]+)</a> received ([\d,]+)x ([^<]+)',
            re.IGNORECASE
        ),
        "returned_item": re.compile(
            r'profiles\.php\?XID=(\d+)">([^<]+)</a>\s+returned\s+([\d,]+)x\s+([^<]+?)\s+to the faction armory',
            re.IGNORECASE
        ),
        "received_from_player": re.compile(
            r'profiles\.php\?XID=(\d+)">([^<]+)</a>\s+received\s+([\d,]+)x\s+([^<]+?)\s+from\s+<a[^>]*profiles\.php\?XID=(\d+)">([^<]+)</a>\s+into the faction armory',
            re.IGNORECASE
        ),
        "retrieved_from_player": re.compile(
            r'profiles\.php\?XID=(\d+)">([^<]+)</a>\s+retrieved\s+([\d,]+)x\s+([^<]+?)\s+from\s+<a[^>]*profiles\.php\?XID=(\d+)">([^<]+)</a>',
            re.IGNORECASE
        ),
    }
    
    # Item ID mapping for Torn API
    # Maps item display names to their Torn API item IDs
    ITEM_ID_MAPPING = {
        # Drugs
        "xanax": 148,
        "morphine": 149,
        "vicodin": 150,
        "tramadol": 151,
        "xtc": 153,
        "ecstasy": 154,
        "ketamine": 155,
        "cocaine": 156,
        "marijuana": 157,
        "cannabis": 157,
        "opium": 158,
        "lsd": 159,
        "pcp": 160,

        # Candy / consumables
        "lollipop": 310,
        "pixie sticks": 151,
        "bag of bon bons": 37,
        "bag of candy kisses": 527,
        "bag of cheetos": 353,
        "bag of chocolate kisses": 210,
        "bag of chocolate truffles": 529,
        "bag of humbugs": 1039,
        "bag of reindeer droppings": 556,
        "bag of sherbet": 587,
        "bag of tootsie rolls": 528,
        "box of bon bons": 38,
        "box of chocolate bars": 35,
        "box of extra strong mints": 39,
        "box of sweet hearts": 209,

        # Bottles / cans
        "bottle of beer": 180,
        "bottle of champagne": 181,
        "bottle of christmas cocktail": 638,
        "bottle of christmas spirit": 924,
        "bottle of green stout": 873,
        "bottle of kandy kane": 550,
        "bottle of minty mayhem": 551,
        "bottle of mistletoe madness": 552,
        "bottle of moonshine": 984,
        "bottle of pumpkin brew": 531,
        "bottle of sake": 294,
        "bottle of stinky swamp punch": 541,
        "bottle of tequila": 426,
        "bottle of wicked witch": 542,
        "can of crocozade": 987,
        "can of damp valley": 986,
        "can of goose juice": 985,
        "can of munster": 530,
        "can of red cow": 532,
        "can of rockstar rudolph": 554,
        "can of santa shooters": 553,
        "can of taurine elite": 533,
        "can of x-mass": 555,
        
        # Medical
        "empty blood bag": 161,
        "blood bag": 162,
        "blood bag : b+": 163,
        "blood bag : b-": 164,
        "blood bag : o+": 165,
        "blood bag : o-": 166,
        "blood bag : a+": 167,
        "blood bag : a-": 168,
        "blood bag : ab+": 169,
        "blood bag : ab-": 170,
        
        # Utilities & Others
        "lockpick": 2,
        "crowbar": 3,
        "atm key": 1379,
        "card skimmer": 1125,

        # Weapons
        "bt mp9": 233,
        "chainsaw": 10,
        "dagger": 7,
        "lead pipe": 401,

        # Temporary
        "heg": 242,
        "grenade": 220,
        "flash grenade": 222,
        "smoke grenade": 226,
        "pepper spray": 392,
        "tear gas": 256,
        "concussion grenade": 1042,
        "molotov cocktail": 742,

        # Extended mappings from Torn item catalogue (previous Unknown bucket)
        "axe": 8,
        "baseball bat": 2,
        "beretta m9": 15,
        "binoculars": 1258,
        "blowgun": 244,
        "blowtorch": 1320,
        "blunderbuss": 490,
        "bolt cutters": 159,
        "bulletproof vest": 34,
        "c4 explosive": 190,
        "cpu": 1301,
        "cassock": 1313,
        "cattle prod": 1257,
        "cemetery key": 853,
        "chain mail": 176,
        "chloroform": 576,
        "cigar cutter": 1223,
        "claymore mine": 229,
        "claymore sword": 217,
        "computer fan": 1303,
        "core drill": 1431,
        "cut-throat razor": 567,
        "dslr camera": 1383,
        "dental mirror": 1284,
        "desert eagle": 20,
        "diamond bladed knife": 614,
        "diesel": 1458,
        "disposable mask": 1143,
        "dog treats": 1361,
        "fine chisel": 359,
        "firewalk virus": 103,
        "fireworks": 246,
        "flak jacket": 178,
        "flamethrower": 255,
        "gasoline": 172,
        "glasses": 564,
        "hiking boots": 646,
        "hydrogen tank": 1459,
        "jemmy": 568,
        "kerosene": 1457,
        "kevlar gloves": 640,
        "kodachi": 237,
        "large suitcase": 421,
        "lawyer's business card": 368,
        "leather boots": 649,
        "leather helmet": 647,
        "leather vest": 32,
        "luger": 489,
        "m16 a2 rifle": 29,
        "m249 saw": 31,
        "m4a1 colt carbine": 27,
        "mp5 navy": 24,
        "macana": 391,
        "mag 7": 225,
        "magnum": 19,
        "medium suitcase": 420,
        "megaphone": 1353,
        "metal detector": 852,
        "metal nunchaku": 395,
        "methane tank": 1460,
        "minigun": 63,
        "net": 1362,
        "p90": 25,
        "pkm": 1155,
        "pen knife": 5,
        "pillow": 440,
        "police badge": 1350,
        "police vest": 33,
        "polymorphic virus": 70,
        "qsz-92": 248,
        "rf detector": 1380,
        "razor wire": 1259,
        "riot gloves": 659,
        "rope": 1201,
        "s&w revolver": 189,
        "sig 550": 232,
        "sig 552": 398,
        "safety boots": 645,
        "sawed-off shotgun": 22,
        "scalpel": 846,
        "scimitar": 9,
        "shaped charge": 1430,
        "shaving foam": 1217,
        "shovel": 1234,
        "spear": 227,
        "speed": 204,
        "spray paint : black": 856,
        "spray paint : blue": 860,
        "spray paint : green": 861,
        "spray paint : orange": 863,
        "spray paint : red": 857,
        "spray paint : white": 862,
        "swiss army knife": 224,
        "tmp": 486,
        "taser": 175,
        "thermite": 1461,
        "thompson": 487,
        "toner": 1290,
        "torn city times": 886,
        "trout": 616,
        "tunneling virus": 71,
        "usp": 16,
        "vektor cr-21": 228,
        "wire cutters": 981,
        "wireless dongle": 579,
        "xm8 rifle": 174,
        "zip ties": 1429,
        "bank statement": 883,
        "hammer": 1,
    }
    
    # Item category mapping
    ITEM_CATEGORIES = {
        # Medical items (bandages, first aid)
        "morphine": "Medical",
        "ipecac syrup": "Medical",
        "empty blood bag": "Medical",
        "blood bag": "Medical",
        "small first aid kit": "Medical",
        "first aid kit": "Medical",
        "large first aid kit": "Medical",
        "aspirin": "Medical",
        "paracetamol": "Medical",
        
        # Drugs (controlled substances - xanax, morphine, etc.)
        "xanax": "Drug",
        "tramadol": "Drug",
        "vicodin": "Drug",
        "xtc": "Drug",
        "ecstasy": "Drug",
        "ketamine": "Drug",
        "cocaine": "Drug",
        "marijuana": "Drug",
        "cannabis": "Drug",
        "opium": "Drug",
        "lsd": "Drug",
        "pcp": "Drug",
        
        # Consumables
        "bottle of ": "Consumable",
        "can of ": "Consumable",
        "lollipop": "Consumable",
        "pixie sticks": "Consumable",
        "bag of bon bons": "Consumable",
        "bag of candy kisses": "Consumable",
        "bag of cheetos": "Consumable",
        "bag of chocolate kisses": "Consumable",
        "bag of chocolate truffles": "Consumable",
        "bag of humbugs": "Consumable",
        "bag of reindeer droppings": "Consumable",
        "bag of sherbet": "Consumable",
        "bag of tootsie rolls": "Consumable",
        "box of bon bons": "Consumable",
        "box of chocolate bars": "Consumable",
        "box of extra strong mints": "Consumable",
        "box of sweet hearts": "Consumable",

        # Utilities (crime/tools)
        "lockpick": "Utility",
        "crowbar": "Utility",
        "keycard": "Utility",
        "cloaking device": "Utility",
        "blank casino chips": "Utility",
        "car battery": "Utility",
        "cell phone": "Utility",
        "credit card": "Utility",
        "id badge": "Utility",
        "wrench": "Utility",
        "atm key": "Utility",
        "card skimmer": "Utility",
        "wireless dongle": "Utility",
        "wire cutters": "Utility",
        "tunneling virus": "Utility",
        "polymorphic virus": "Utility",

        # Temporary
        "heg": "Temporary",
        "grenade": "Temporary",
        "flash grenade": "Temporary",
        "smoke grenade": "Temporary",
        "pepper spray": "Temporary",
        "tear gas": "Temporary",
        "concussion grenade": "Temporary",
        "molotov cocktail": "Temporary",

        # Boosters
        "booster": "Booster",
        "lawyer's business card": "Booster",
        "feather hotel coupon": "Booster",
        "hotel coupon": "Booster",
        
        # Armor
        "combat helmet": "Armor",
        "combat gloves": "Armor",
        "combat pants": "Armor",
        "combat vest": "Armor",
        "combat boots": "Armor",
        "leather gloves": "Armor",
        "construction helmet": "Armor",
        "leather pants": "Armor",

        # Weapons
        "skorpion": "Weapon",
        "glock 17": "Weapon",
        "ak-47": "Weapon",
        "benelli m4 super": "Weapon",
        "jackhammer": "Weapon",
        "butterfly knife": "Weapon",
        "enfield sa-80": "Weapon",
        "fiveseven": "Weapon",
        "mp5k": "Weapon",
        "tavor tar-21": "Weapon",
        "bt mp9": "Weapon",
        "chainsaw": "Weapon",
        "dagger": "Weapon",
        "lead pipe": "Weapon",

        # Extended category mappings from Torn item types
        "desert eagle": "Weapon",
        "blowgun": "Weapon",
        "blunderbuss": "Weapon",
        "claymore sword": "Weapon",
        "diamond bladed knife": "Weapon",
        "fine chisel": "Weapon",
        "flamethrower": "Weapon",
        "kodachi": "Weapon",
        "luger": "Weapon",
        "m16 a2 rifle": "Weapon",
        "m249 saw": "Weapon",
        "m4a1 colt carbine": "Weapon",
        "mp5 navy": "Weapon",
        "macana": "Weapon",
        "mag 7": "Weapon",
        "magnum": "Weapon",
        "metal nunchaku": "Weapon",
        "minigun": "Weapon",
        "p90": "Weapon",
        "pkm": "Weapon",
        "qsz-92": "Weapon",
        "s&w revolver": "Weapon",
        "sig 550": "Weapon",
        "sig 552": "Weapon",
        "sawed-off shotgun": "Weapon",
        "scimitar": "Weapon",
        "spear": "Weapon",
        "tmp": "Weapon",
        "taser": "Weapon",
        "thompson": "Weapon",
        "usp": "Weapon",
        "vektor cr-21": "Weapon",
        "xm8 rifle": "Weapon",
        "axe": "Weapon",
        "hammer": "Weapon",
        "baseball bat": "Weapon",
        "beretta m9": "Weapon",
        "cattle prod": "Weapon",
        "pen knife": "Weapon",
        "pillow": "Weapon",
        "scalpel": "Weapon",
        "swiss army knife": "Weapon",

        "bulletproof vest": "Armor",
        "chain mail": "Armor",
        "flak jacket": "Armor",
        "hiking boots": "Armor",
        "kevlar gloves": "Armor",
        "leather boots": "Armor",
        "leather helmet": "Armor",
        "leather vest": "Armor",
        "police vest": "Armor",
        "riot gloves": "Armor",
        "safety boots": "Armor",

        "claymore mine": "Temporary",
        "fireworks": "Temporary",
        "trout": "Temporary",

        "speed": "Drug",

        "binoculars": "Utility",
        "blowtorch": "Utility",
        "bolt cutters": "Utility",
        "c4 explosive": "Utility",
        "cpu": "Utility",
        "cassock": "Utility",
        "cemetery key": "Utility",
        "chloroform": "Utility",
        "cigar cutter": "Utility",
        "computer fan": "Utility",
        "core drill": "Utility",
        "cut-throat razor": "Utility",
        "dslr camera": "Utility",
        "dental mirror": "Utility",
        "diesel": "Utility",
        "disposable mask": "Utility",
        "dog treats": "Utility",
        "firewalk virus": "Utility",
        "gasoline": "Utility",
        "glasses": "Utility",
        "hydrogen tank": "Utility",
        "jemmy": "Utility",
        "kerosene": "Utility",
        "large suitcase": "Utility",
        "medium suitcase": "Utility",
        "megaphone": "Utility",
        "metal detector": "Utility",
        "methane tank": "Utility",
        "net": "Utility",
        "police badge": "Utility",
        "polymorphic virus": "Utility",
        "rf detector": "Utility",
        "razor wire": "Utility",
        "rope": "Utility",
        "shaped charge": "Utility",
        "shaving foam": "Utility",
        "shovel": "Utility",
        "spray paint : black": "Utility",
        "spray paint : blue": "Utility",
        "spray paint : green": "Utility",
        "spray paint : orange": "Utility",
        "spray paint : red": "Utility",
        "spray paint : white": "Utility",
        "thermite": "Utility",
        "toner": "Utility",
        "torn city times": "Utility",
        "tunneling virus": "Utility",
        "wire cutters": "Utility",
        "wireless dongle": "Utility",
        "zip ties": "Utility",
        "bank statement": "Utility",

        # Weapons/Armor handled separately
    }
    
    @staticmethod
    def clean_html(text):
        """Remove HTML tags and decode entities"""
        text = re.sub(r'<[^>]+>', '', text)
        return unescape(text).strip()
    
    @staticmethod
    def get_item_category(item_name):
        """Determine item category from name"""
        name_lower = item_name.lower()
        
        # Check direct matches
        for item_key, category in ArmouryParser.ITEM_CATEGORIES.items():
            if item_key in name_lower:
                return category
        
        # Heuristic checks (fallback)
        if any(med in name_lower for med in ["morphine", "ipecac syrup", "blood bag", "first aid", "bandage", "aspirin", "paracetamol"]):
            return "Medical"
        elif any(drug in name_lower for drug in ["xanax", "tramadol", "vicodin", "xtc", "ecstasy", "cocaine", "marijuana", "cannabis", "opium", "lsd", "pcp", "ketamine"]):
            return "Drug"
        elif any(consumable in name_lower for consumable in ["bottle of ", "can of ", "bag of ", "box of ", "lollipop", "pixie sticks", "chocolate", "candy", "beer", "champagne", "moonshine"]):
            return "Consumable"
        elif any(tmp in name_lower for tmp in ["pepper spray", "flash grenade", "smoke grenade", "concussion grenade", "tear gas", "molotov", " heg", "grenade"]):
            return "Temporary"
        elif any(util in name_lower for util in ["lockpick", "crowbar", "keycard", "device", "casino chips", "car battery", "cell phone", "credit card", "id badge", "wrench", "atm key", "card skimmer", "wire cutters", "bolt cutters", "rf detector", "metal detector", "blowtorch", "core drill", "shaped charge", "zip ties"]):
            return "Utility"
        elif any(armor in name_lower for armor in ["combat helmet", "combat gloves", "combat pants", "combat vest", "combat boots", "leather gloves", "construction helmet", "leather pants", "armor", "armour"]):
            return "Armor"
        elif any(weapon in name_lower for weapon in ["skorpion", "glock", "ak-47", "benelli", "jackhammer", "butterfly knife", "enfield", "fiveseven", "mp5k", "tavor", "bt mp9", "chainsaw", "dagger", "lead pipe", "weapon"]):
            return "Weapon"
        elif "booster" in name_lower:
            return "Booster"
        
        return "Unknown"

    @classmethod
    def get_category_from_api_type(cls, item_type):
        """Map Torn API item type to local category."""
        if not item_type:
            return "Unknown"
        return cls.TYPE_TO_CATEGORY.get(str(item_type).strip().lower(), "Unknown")
    
    @staticmethod
    def get_item_id(item_name):
        """Get Torn API item ID from item name"""
        name_lower = item_name.lower()
        
        # Check direct matches first (most specific)
        for item_key, item_id in ArmouryParser.ITEM_ID_MAPPING.items():
            if item_key.lower() == name_lower:
                return item_id
        
        # Check partial matches (for blood bag variants)
        for item_key, item_id in ArmouryParser.ITEM_ID_MAPPING.items():
            if item_key.lower() in name_lower:
                return item_id
        
        # Default: 0 (unknown)
        return 0
    
    @classmethod
    def parse(cls, event_id, event_data):
        """
        Parse armoury news event.
        
        Args:
            event_id: Event ID from API
            event_data: Event dict with 'news' (HTML) and 'timestamp'
        
        Returns:
            Dict with parsed event or None if not recognized
        """
        news = event_data.get("news", "")
        timestamp = int(event_data.get("timestamp", 0) or 0)
        
        # Try each pattern
        for event_type, pattern in cls.PATTERNS.items():
            match = pattern.search(news)
            if not match:
                continue
            
            # Parse based on event type
            if event_type == "loaned_to_player":
                lender_id = int(match.group(1))
                lender_name = match.group(2)
                quantity = int(match.group(3).replace(",", ""))
                item_name = match.group(4)
                recipient_id = int(match.group(5))
                recipient_name = match.group(6)

                item_category = cls.get_item_category(item_name)
                item_id = cls.get_item_id(item_name)

                return {
                    "event_id": event_id,
                    "timestamp": timestamp,
                    # Track who currently holds the loaned item.
                    "player_id": recipient_id,
                    "player_name": recipient_name,
                    "event_type": "loaned",
                    "item_id": item_id,
                    "item_name": item_name,
                    "item_category": item_category,
                    "quantity": quantity,
                    "description": f"{lender_name} loaned {quantity}x {item_name} to {recipient_name}",
                    "raw_news": news,
                    "item_price": 0,
                    "price_source": "unknown",
                }

            elif event_type == "used_faction_item":
                player_id = int(match.group(1))
                player_name = match.group(2)
                item_name = match.group(3)
                
                item_category = cls.get_item_category(item_name)
                item_id = cls.get_item_id(item_name)
                
                return {
                    "event_id": event_id,
                    "timestamp": timestamp,
                    "player_id": player_id,
                    "player_name": player_name,
                    "event_type": "used",
                    "item_id": item_id,
                    "item_name": item_name,
                    "item_category": item_category,
                    "quantity": 1,
                    "description": f"{player_name} used {item_name}",
                    "raw_news": news,
                    "item_price": 0,  # Will be filled in by service
                    "price_source": "unknown",
                }
            
            elif event_type == "filled_blood_bag":
                player_id = int(match.group(1))
                player_name = match.group(2)
                
                item_name = "Empty Blood Bag"
                item_category = "Medical"
                item_id = cls.get_item_id(item_name)
                
                return {
                    "event_id": event_id,
                    "timestamp": timestamp,
                    "player_id": player_id,
                    "player_name": player_name,
                    "event_type": "filled",
                    "item_id": item_id,
                    "item_name": item_name,
                    "item_category": item_category,
                    "quantity": 1,
                    "description": f"{player_name} filled an Empty Blood Bag",
                    "raw_news": news,
                    "item_price": 0,
                    "price_source": "unknown",
                }
            
            elif event_type == "deposited":
                player_id = int(match.group(1))
                player_name = match.group(2)
                quantity = int(match.group(3).replace(",", ""))
                item_name = match.group(4)
                
                item_category = cls.get_item_category(item_name)
                item_id = cls.get_item_id(item_name)
                
                return {
                    "event_id": event_id,
                    "timestamp": timestamp,
                    "player_id": player_id,
                    "player_name": player_name,
                    "event_type": "deposited",
                    "item_id": item_id,
                    "item_name": item_name,
                    "item_category": item_category,
                    "quantity": quantity,
                    "description": f"{player_name} deposited {quantity}x {item_name}",
                    "raw_news": news,
                    "item_price": 0,
                    "price_source": "unknown",
                }
            
            elif event_type in ("sent_item", "received_item"):
                player_id = int(match.group(1))
                player_name = match.group(2)
                quantity = int(match.group(3).replace(",", ""))
                item_name = match.group(4)
                
                item_category = cls.get_item_category(item_name)
                item_id = cls.get_item_id(item_name)
                event_action = "loaned" if event_type == "sent_item" else "received"
                
                return {
                    "event_id": event_id,
                    "timestamp": timestamp,
                    "player_id": player_id,
                    "player_name": player_name,
                    "event_type": event_action,
                    "item_id": item_id,
                    "item_name": item_name,
                    "item_category": item_category,
                    "quantity": quantity,
                    "description": f"{player_name} {event_action} {quantity}x {item_name}",
                    "raw_news": news,
                    "item_price": 0,
                    "price_source": "unknown",
                }

            elif event_type == "returned_item":
                player_id = int(match.group(1))
                player_name = match.group(2)
                quantity = int(match.group(3).replace(",", ""))
                item_name = match.group(4)

                item_category = cls.get_item_category(item_name)
                item_id = cls.get_item_id(item_name)

                return {
                    "event_id": event_id,
                    "timestamp": timestamp,
                    "player_id": player_id,
                    "player_name": player_name,
                    # Normalize returns into the same balancing type used by tracker.
                    "event_type": "received",
                    "item_id": item_id,
                    "item_name": item_name,
                    "item_category": item_category,
                    "quantity": quantity,
                    "description": f"{player_name} returned {quantity}x {item_name} to the faction armory",
                    "raw_news": news,
                    "item_price": 0,
                    "price_source": "unknown",
                }

            elif event_type == "received_from_player":
                receiver_id = int(match.group(1))
                receiver_name = match.group(2)
                quantity = int(match.group(3).replace(",", ""))
                item_name = match.group(4)
                source_id = int(match.group(5))
                source_name = match.group(6)

                item_category = cls.get_item_category(item_name)
                item_id = cls.get_item_id(item_name)

                return {
                    "event_id": event_id,
                    "timestamp": timestamp,
                    # Track the source player as returning the item.
                    "player_id": source_id,
                    "player_name": source_name,
                    "event_type": "received",
                    "item_id": item_id,
                    "item_name": item_name,
                    "item_category": item_category,
                    "quantity": quantity,
                    "description": f"{receiver_name} received {quantity}x {item_name} from {source_name}",
                    "raw_news": news,
                    "item_price": 0,
                    "price_source": "unknown",
                }

            elif event_type == "retrieved_from_player":
                receiver_id = int(match.group(1))
                receiver_name = match.group(2)
                quantity = int(match.group(3).replace(",", ""))
                item_name = match.group(4)
                source_id = int(match.group(5))
                source_name = match.group(6)

                item_category = cls.get_item_category(item_name)
                item_id = cls.get_item_id(item_name)

                return {
                    "event_id": event_id,
                    "timestamp": timestamp,
                    # Track the source player as returning the item.
                    "player_id": source_id,
                    "player_name": source_name,
                    "event_type": "received",
                    "item_id": item_id,
                    "item_name": item_name,
                    "item_category": item_category,
                    "quantity": quantity,
                    "description": f"{receiver_name} retrieved {quantity}x {item_name} from {source_name}",
                    "raw_news": news,
                    "item_price": 0,
                    "price_source": "unknown",
                }
        
        # No pattern matched
        return None
