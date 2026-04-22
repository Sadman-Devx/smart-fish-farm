"""
farm/bd_geo.py
─────────────────────────────────────────────────────────────────────────────
Bangladesh districts and their upazilas.
Used in the onboarding location fallback when GPS is denied.

Data covers all 64 districts with their upazilas.
Kept as a plain Python dict so it has zero external dependencies.
"""

DISTRICTS: dict[str, list[str]] = {
    "Bagerhat": [
        "Bagerhat Sadar", "Chitalmari", "Fakirhat", "Kachua", "Mollahat",
        "Mongla", "Morrelganj", "Rampal", "Sarankhola",
    ],
    "Bandarban": [
        "Ali Kadam", "Bandarban Sadar", "Lama", "Naikhongchhari",
        "Rowangchhari", "Ruma", "Thanchi",
    ],
    "Barguna": [
        "Amtali", "Bamna", "Barguna Sadar", "Betagi", "Patharghata", "Taltali",
    ],
    "Barisal": [
        "Agailjhara", "Babuganj", "Bakerganj", "Banaripara", "Barisal Sadar",
        "Gaurnadi", "Hizla", "Mehendiganj", "Muladi", "Wazirpur",
    ],
    "Bhola": [
        "Bhola Sadar", "Burhanuddin", "Char Fasson", "Daulatkhan",
        "Lalmohan", "Manpura", "Tazumuddin",
    ],
    "Bogura": [
        "Adamdighi", "Bogura Sadar", "Dhunat", "Dhupchanchia", "Gabtali",
        "Kahaloo", "Nandigram", "Sariakandi", "Shajahanpur", "Sherpur",
        "Shibganj", "Sonatala",
    ],
    "Brahmanbaria": [
        "Akhaura", "Ashuganj", "Bancharampur", "Brahmanbaria Sadar",
        "Bijoynagar", "Kasba", "Nabinagar", "Nasirnagar", "Sarail",
    ],
    "Chandpur": [
        "Chandpur Sadar", "Faridganj", "Haimchar", "Haziganj",
        "Kachua", "Matlab Dakshin", "Matlab Uttar", "Shahrasti",
    ],
    "Chapai Nawabganj": [
        "Bholahat", "Chapai Nawabganj Sadar", "Gomastapur",
        "Nachole", "Shibganj",
    ],
    "Chattogram": [
        "Anwara", "Banshkhali", "Boalkhali", "Chandanaish", "Chattogram Sadar",
        "Fatikchhari", "Hathazari", "Karnaphuli", "Kotwali", "Lohagara",
        "Mirsharai", "Patiya", "Rangunia", "Raozan", "Sandwip",
        "Satkania", "Sitakunda",
    ],
    "Chuadanga": [
        "Alamdanga", "Chuadanga Sadar", "Damurhuda", "Jibannagar",
    ],
    "Cox's Bazar": [
        "Chakaria", "Cox's Bazar Sadar", "Kutubdia", "Maheshkhali",
        "Pekua", "Ramu", "Teknaf", "Ukhia",
    ],
    "Cumilla": [
        "Barura", "Brahmanpara", "Burichang", "Chandina", "Chauddagram",
        "Cumilla Adarsha Sadar", "Cumilla Sadar Dakshin", "Daudkandi",
        "Debidwar", "Homna", "Laksam", "Lalmai", "Manoharganj",
        "Meghna", "Monohargonj", "Muradnagar", "Nangalkot", "Titas",
    ],
    "Dhaka": [
        "Dhamrai", "Dohar", "Keraniganj", "Nawabganj", "Savar",
    ],
    "Dinajpur": [
        "Birampur", "Birganj", "Biral", "Bochaganj", "Chirirbandar",
        "Dinajpur Sadar", "Fulbari", "Ghoraghat", "Hakimpur",
        "Kaharole", "Khansama", "Nawabganj", "Parbatipur",
    ],
    "Faridpur": [
        "Alfadanga", "Bhanga", "Boalmari", "Charbhadrasan", "Faridpur Sadar",
        "Madhukhali", "Nagarkanda", "Sadarpur", "Saltha",
    ],
    "Feni": [
        "Chagalnaiya", "Daganbhuiyan", "Feni Sadar", "Fulgazi",
        "Parshuram", "Sonagazi",
    ],
    "Gaibandha": [
        "Fulchhari", "Gaibandha Sadar", "Gobindaganj", "Palashbari",
        "Sadullapur", "Saghata", "Sundarganj",
    ],
    "Gazipur": [
        "Gazipur Sadar", "Kaliakair", "Kaliganj", "Kapasia", "Sreepur",
    ],
    "Gopalganj": [
        "Gopalganj Sadar", "Kashiani", "Kotalipara", "Muksudpur", "Tungipara",
    ],
    "Habiganj": [
        "Ajmiriganj", "Bahubal", "Baniachong", "Chunarughat", "Habiganj Sadar",
        "Lakhai", "Madhabpur", "Nabiganj",
    ],
    "Jamalpur": [
        "Bakshiganj", "Dewanganj", "Islampur", "Jamalpur Sadar",
        "Madarganj", "Melandaha", "Sarishabari",
    ],
    "Jashore": [
        "Abhaynagar", "Bagherpara", "Chaugachha", "Jhikargacha",
        "Jashore Sadar", "Keshbpur", "Manirampur", "Sharsha",
    ],
    "Jhalokati": [
        "Jhalokati Sadar", "Kanthalia", "Nalchity", "Rajapur",
    ],
    "Jhenaidah": [
        "Harinakunda", "Jhenaidah Sadar", "Kaliganj", "Kotchandpur",
        "Maheshpur", "Shailkupa",
    ],
    "Joypurhat": [
        "Akkelpur", "Joypurhat Sadar", "Kalai", "Khetlal", "Panchbibi",
    ],
    "Khagrachhari": [
        "Dighinala", "Guimara", "Khagrachhari Sadar", "Lakshmichhari",
        "Mahalchhari", "Manikchhari", "Matiranga", "Panchhari", "Ramgarh",
    ],
    "Khulna": [
        "Batiaghata", "Dacope", "Daulatpur", "Dumuria", "Dighalia",
        "Khalishpur", "Khan Jahan Ali", "Khulna Sadar", "Koyra",
        "Paikgachha", "Phultala", "Rupsa", "Terokhada",
    ],
    "Kishoreganj": [
        "Austagram", "Bajitpur", "Bhairab", "Hossainpur", "Itna",
        "Karimganj", "Katiadi", "Kishoreganj Sadar", "Kuliarchar",
        "Mithamain", "Nikli", "Pakundia", "Tarail",
    ],
    "Kurigram": [
        "Bhurungamari", "Char Rajibpur", "Chilmari", "Kurigram Sadar",
        "Nageshwari", "Phulbari", "Rajibpur", "Rajarhat", "Rowmari", "Ulipur",
    ],
    "Kushtia": [
        "Bheramara", "Daulatpur", "Khoksa", "Kumarkhali", "Kushtia Sadar", "Mirpur",
    ],
    "Lakshmipur": [
        "Kamalnagar", "Lakshmipur Sadar", "Ramganj", "Ramgati", "Roypur",
    ],
    "Lalmonirhat": [
        "Aditmari", "Hatibandha", "Kaliganj", "Lalmonirhat Sadar", "Patgram",
    ],
    "Madaripur": [
        "Kalkini", "Madaripur Sadar", "Rajoir", "Shibchar",
    ],
    "Magura": [
        "Magura Sadar", "Mohammadpur", "Shalikha", "Sreepur",
    ],
    "Manikganj": [
        "Daulatpur", "Ghior", "Harirampur", "Manikganj Sadar",
        "Saturia", "Shivalaya", "Singair",
    ],
    "Meherpur": [
        "Gangni", "Meherpur Sadar", "Mujibnagar",
    ],
    "Moulvibazar": [
        "Barlekha", "Juri", "Kamalganj", "Kulaura", "Moulvibazar Sadar",
        "Rajnagar", "Sreemangal",
    ],
    "Munshiganj": [
        "Gazaria", "Louhajang", "Munshiganj Sadar", "Sirajdikhan",
        "Sreenagar", "Tongibari",
    ],
    "Mymensingh": [
        "Bhaluka", "Dhobaura", "Fulbaria", "Gaffargaon", "Gauripur",
        "Haluaghat", "Ishwarganj", "Muktagachha", "Mymensingh Sadar",
        "Nandail", "Phulpur", "Trishal",
    ],
    "Naogaon": [
        "Atrai", "Badalgachhi", "Dhamoirhat", "Manda", "Mahadebpur",
        "Naogaon Sadar", "Niamatpur", "Patnitala", "Porsha", "Raninagar", "Sapahar",
    ],
    "Narail": [
        "Kalia", "Lohagara", "Narail Sadar",
    ],
    "Narayanganj": [
        "Araihazar", "Bandar", "Narayanganj Sadar", "Rupganj", "Sonargaon",
    ],
    "Narsingdi": [
        "Belabo", "Monohardi", "Narsingdi Sadar", "Palash", "Raipura", "Shibpur",
    ],
    "Natore": [
        "Bagatipara", "Baraigram", "Gurudaspur", "Lalpur",
        "Natore Sadar", "Singra",
    ],
    "Netrokona": [
        "Atpara", "Barhatta", "Durgapur", "Kalmakanda", "Kendua",
        "Khaliajuri", "Madan", "Mohanganj", "Netrokona Sadar", "Purbadhala",
    ],
    "Nilphamari": [
        "Dimla", "Domar", "Jaldhaka", "Kishoreganj", "Nilphamari Sadar", "Saidpur",
    ],
    "Noakhali": [
        "Begumganj", "Chatkhil", "Companiganj", "Hatiya", "Kabirhat",
        "Noakhali Sadar", "Senbagh", "Sonaimuri", "Subarnachar",
    ],
    "Pabna": [
        "Atgharia", "Bera", "Bhangura", "Chatmohar", "Faridpur",
        "Ishwardi", "Pabna Sadar", "Santhia", "Sujanagar",
    ],
    "Panchagarh": [
        "Atwari", "Boda", "Debiganj", "Panchagarh Sadar", "Tetulia",
    ],
    "Patuakhali": [
        "Bauphal", "Dashmina", "Dumki", "Galachipa", "Kalapara",
        "Mirzaganj", "Patuakhali Sadar", "Rangabali",
    ],
    "Pirojpur": [
        "Bhandaria", "Kawkhali", "Mathbaria", "Nazirpur",
        "Pirojpur Sadar", "Zianagar",
    ],
    "Rajbari": [
        "Baliakandi", "Goalanda", "Kalukhali", "Pangsha", "Rajbari Sadar",
    ],
    "Rajshahi": [
        "Bagha", "Bagmara", "Boalia", "Charghat", "Durgapur", "Godagari",
        "Matihar", "Mohanpur", "Paba", "Puthia", "Rajpara", "Shaheb Bazar", "Tanore",
    ],
    "Rangamati": [
        "Bagaichhari", "Barkal", "Belaichhari", "Juraichhari", "Kaptai",
        "Kaukhali", "Langadu", "Naniarchar", "Rajasthali", "Rangamati Sadar",
    ],
    "Rangpur": [
        "Badarganj", "Gangachara", "Kaunia", "Mithapukur", "Pirgachha",
        "Pirganj", "Rangpur Sadar", "Taraganj",
    ],
    "Satkhira": [
        "Assasuni", "Debhata", "Kalaroa", "Kaliganj", "Satkhira Sadar",
        "Shyamnagar", "Tala",
    ],
    "Shariatpur": [
        "Bhedarganj", "Damuddya", "Gosairhat", "Jajira",
        "Naria", "Shariatpur Sadar",
    ],
    "Sherpur": [
        "Jhenaigati", "Nakla", "Nalitabari", "Sherpur Sadar", "Sreebardi",
    ],
    "Sirajganj": [
        "Belkuchi", "Chauhali", "Kamarkhanda", "Kazipur", "Raiganj",
        "Shahjadpur", "Sirajganj Sadar", "Tarash", "Ullapara",
    ],
    "Sunamganj": [
        "Bishwamvarpur", "Chhatak", "Derai", "Dharampasha", "Dowarabazar",
        "Jagannathpur", "Jamalganj", "Sullah", "Sunamganj Sadar",
        "Shalla", "Tahirpur",
    ],
    "Sylhet": [
        "Beanibazar", "Bishwanath", "Companiganj", "Fenchuganj",
        "Golapganj", "Gowainghat", "Jaintiapur", "Kanaighat",
        "Osmani Nagar", "South Surma", "Sylhet Sadar", "Zakiganj",
    ],
    "Tangail": [
        "Basail", "Bhuapur", "Delduar", "Dhanbari", "Ghatail", "Gopalpur",
        "Kalihati", "Madhupur", "Mirzapur", "Nagarpur", "Sakhipur",
        "Tangail Sadar",
    ],
    "Thakurgaon": [
        "Baliadangi", "Haripur", "Pirganj", "Ranisankail", "Thakurgaon Sadar",
    ],
}

# Sorted district names for use in form choices
DISTRICT_CHOICES: list[tuple[str, str]] = [("", "— Select District —")] + [
    (d, d) for d in sorted(DISTRICTS.keys())
]


def get_upazila_choices(district: str) -> list[tuple[str, str]]:
    """Return (value, label) upazila choices for a given district name."""
    upazilas = DISTRICTS.get(district, [])
    return [("", "— Select Upazila —")] + [(u, u) for u in sorted(upazilas)]