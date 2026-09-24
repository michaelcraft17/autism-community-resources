#!/usr/bin/env python3
"""
National and regional autism organizations across Europe, sourced from
Autism-Europe's own official member directory PDF (an umbrella federation's
verified member list, not a scraped or LLM-narrated source):

    https://www.autismeurope.org/wp-content/uploads/2023/04/Members-associations-of-Autism-Europe_2023.pdf

Every name/address/website below is transcribed verbatim from that PDF. This
is a one-off curated list rather than a live API pull because Autism-Europe
doesn't expose one -- but the source document itself is official and
structured (a federation's own membership register), same tier of
reliability as tools/cqc_uk_fetch.py's government CSV, just not machine-
queryable at the source.

First pass (prior session) covered only Germany/Sweden/Lithuania/Russia. This
pass adds every other Full/Associate/Affiliated member in the directory that
has a usable name+address (a handful of entries with no real website and only
a Facebook page or "under construction" link, e.g. Republic of Belarus's LSPA
and Italy's Fondazione Il Domani Dell'autismo, are skipped -- not worth a
placeless entry with zero verifiable contact info). China/Russia beyond what
Autism-Europe covers (Russia has 3 members total, already fully captured) are
out of scope for this file -- see HANDOFF.md for that investigation.
Duplicates against entries already in community_resources.json (e.g. UK's
National Autistic Society, likely already present from an earlier UK-specific
pull) are handled automatically by tools/merge_new_resources.py's name/domain
dedup -- no need to hand-filter here.

Usage:
    python3 tools/autism_europe_members_fetch.py

Writes:
    new_resources_autism_europe_members.json   final resource-schema output (repo root)
"""
import json
import os
import time
import urllib.parse
import urllib.request

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_PATH = os.path.join(REPO, "new_resources_autism_europe_members.json")

HEADERS = {"User-Agent": "autism-community-resources-research/1.0 (contact: michaelcraft17@gmail.com)"}
NOMINATIM = "https://nominatim.openstreetmap.org/search"

SOURCE_PDF = "Autism-Europe official member directory (2023 PDF)"

ENTRIES = [
    {
        "name": "Autismus Deutschland",
        "address": "Rothenbaumchaussee 15, 20148 Hamburg, Germany",
        "website": "https://www.autismus.de",
        "type": "advocacy",
        "services": ["Advocacy", "Information & Support"],
        "description": "National association of autistic people and parents in Germany; full member of Autism-Europe.",
    },
    {
        "name": "Autism- och Aspergerforbundet (Autism Sweden)",
        "address": "Bellmansgatan 30, 118 47 Stockholm, Sweden",
        "website": "https://www.autism.se",
        "type": "advocacy",
        "services": ["Advocacy", "Information & Support"],
        "description": "National association of autistic people and parents in Sweden; full member of Autism-Europe.",
    },
    {
        "name": "Lietaus vaikai (Rain Children)",
        "address": "Pylimo str. 14A/37, 01117 Vilnius, Lithuania",
        "website": "https://www.lietausvaikai.lt",
        "type": "advocacy",
        "services": ["Advocacy", "Information & Support"],
        "description": "National association of autistic people and parents in Lithuania; full member of Autism-Europe.",
    },
    {
        "name": "Autism Regions Association",
        "address": "90 Dubininskaya str., 115093 Moscow, Russia",
        "website": "https://autism-regions.org",
        "type": "advocacy",
        "services": ["Advocacy", "Information & Support"],
        "description": "National association of autistic people and parents in Russia; full member of Autism-Europe.",
    },
    {
        "name": 'Chuvash Regional Public Organisation for Helping Children with ASD "Wings"',
        "address": "Avtozapravochny pr. 19, Cheboksary, Chuvash Republic, 428003, Russia",
        "website": "http://wings-autism.ru",
        "type": "general_support",
        "services": ["Information & Support", "Family Support"],
        "description": "Regional resource centre in Chuvashia, Russia helping children with autism spectrum disorder; associate member of Autism-Europe.",
    },
    {
        "name": "Our Sunny World (Solnechny Mir)",
        "address": "Leskova 6B, Moscow, 127349, Russia",
        "website": "http://solnechnymir.ru",
        "type": "medical",
        "services": ["Rehabilitation", "Therapy"],
        "description": "Rehabilitation centre for disabled children in Moscow, Russia; associate member of Autism-Europe.",
    },
    # --- Full members: national associations of autistic people and parents ---
    {
        "name": "AUTEA",
        "address": "Carrer Prada Casadet, num. 2, AD500 Andorra la Vella, Andorra",
        "website": "https://www.autea.org",
        "type": "advocacy", "services": ["Advocacy", "Information & Support"],
        "description": "National association of autistic people and parents in Andorra; full member of Autism-Europe.",
    },
    {
        "name": "Association Pour l'Epanouissement des Personnes Autistes (A.P.E.P.A.)",
        "address": "Rue du Fond de Malonne 127, 5020 Malonne, Belgium",
        "website": "http://www.ulg.ac.be/apepa",
        "type": "advocacy", "services": ["Advocacy", "Information & Support"],
        "description": "French-speaking national association for autistic people in Belgium; full member of Autism-Europe.",
    },
    {
        "name": "Vlaamse Vereniging voor Autisme (V.V.A.)",
        "address": "Groot Begijnhof 14, B-9040 Gent, Belgium",
        "website": "https://www.autismevlaanderen.be",
        "type": "advocacy", "services": ["Advocacy", "Information & Support"],
        "description": "Flemish-speaking national association for autistic people in Belgium; full member of Autism-Europe.",
    },
    {
        "name": "Narodni ustav pro autismus (NAUTIS)",
        "address": "V Holesovickach 593/1a, 182 00 Praha, Czech Republic",
        "website": "https://www.nautis.cz",
        "type": "advocacy", "services": ["Advocacy", "Information & Support"],
        "description": "National institute for autism in the Czech Republic; full member of Autism-Europe.",
    },
    {
        "name": "Croatian Union of Associations for Autism",
        "address": "Ljudevita Posavskog 37, 10000 Zagreb, Croatia",
        "website": "https://www.autizam-suzah.hr",
        "type": "advocacy", "services": ["Advocacy", "Information & Support"],
        "description": "National union of autism associations in Croatia; full member of Autism-Europe.",
    },
    {
        "name": "Landsforeningen Autisme",
        "address": "Banestroget 19-21, 2630 Taastrup, Denmark",
        "website": "https://www.autismeforening.dk",
        "type": "advocacy", "services": ["Advocacy", "Information & Support"],
        "description": "National autism association of Denmark; full member of Autism-Europe.",
    },
    {
        "name": "Finnish Association for Autism and Asperger's Syndrome",
        "address": "Pasilanraitio 9 B, 00240 Helsinki, Finland",
        "website": "https://www.autismiliitto.fi",
        "type": "advocacy", "services": ["Advocacy", "Information & Support"],
        "description": "National autism and Asperger's association of Finland; full member of Autism-Europe.",
    },
    {
        "name": "Autisme France",
        "address": "1175 Avenue de la Republique, 06550 La Roquette sur Siagne, France",
        "website": "https://www.autismefrance.org",
        "type": "advocacy", "services": ["Advocacy", "Information & Support"],
        "description": "National autism association of France; full member of Autism-Europe.",
    },
    {
        "name": "Sesame Autisme",
        "address": "53 rue Clisson, 75013 Paris, France",
        "website": "https://sesameautisme.fr",
        "type": "advocacy", "services": ["Advocacy", "Information & Support"],
        "description": "National autism association of France; full member of Autism-Europe.",
    },
    {
        "name": "Greek Society for the Protection of Autistic People (G.S.P.A.P.)",
        "address": "2 Athenas Street, GR-10551 Athens, Greece",
        "website": "https://www.autismgreece.gr",
        "type": "advocacy", "services": ["Advocacy", "Information & Support"],
        "description": "National autism society of Greece; full member of Autism-Europe.",
    },
    {
        "name": "Hungarian Autistic Society (HAS)",
        "address": "Fejer Gyorgy u. 10, 1053 Budapest, Hungary",
        "website": "https://www.esoember.hu",
        "type": "advocacy", "services": ["Advocacy", "Information & Support"],
        "description": "National autistic society of Hungary; full member of Autism-Europe.",
    },
    {
        "name": "Einhverfusamtokin",
        "address": "Haaleitisbraut 11-13, IS-108 Reykjavik, Iceland",
        "website": "https://www.einhverfa.is",
        "type": "advocacy", "services": ["Advocacy", "Information & Support"],
        "description": "National autism association of Iceland; full member of Autism-Europe.",
    },
    {
        "name": "Irish Society For Autism (I.S.A.)",
        "address": "16/17 Lower O'Connell Street, Dublin 1, Ireland",
        "website": "https://www.autism.ie",
        "type": "advocacy", "services": ["Advocacy", "Information & Support"],
        "description": "National autism society of Ireland; full member of Autism-Europe.",
    },
    {
        "name": "Autism Spectrum Information Advice and Meeting Point (AsIAm)",
        "address": "17-21 Temple Road, Blackrock, Co Dublin, A94DN40, Ireland",
        "website": "https://asiam.ie",
        "type": "advocacy", "services": ["Advocacy", "Information & Support"],
        "description": "National autism advocacy and information organization in Ireland; full member of Autism-Europe.",
    },
    {
        "name": "ANGSA APS Onlus",
        "address": "Via Casal Bruciato 13, 00159 Roma, Italy",
        "website": "https://angsa.it",
        "type": "advocacy", "services": ["Advocacy", "Information & Support"],
        "description": "National association of parents of autistic people in Italy; full member of Autism-Europe.",
    },
    {
        "name": "Fondation Autisme Luxembourg",
        "address": "68 route d'Arlon, L-8310 Capellen, Luxembourg",
        "website": "https://www.fal.lu",
        "type": "advocacy", "services": ["Advocacy", "Information & Support"],
        "description": "National autism foundation of Luxembourg; full member of Autism-Europe.",
    },
    {
        "name": "Autism Parents Association (APA)",
        "address": "P.O. Box 30, Marsa, MTP 1001, Malta",
        "website": "http://www.autismparentsassociation.com",
        "type": "advocacy", "services": ["Advocacy", "Information & Support"],
        "description": "National autism parents association of Malta; full member of Autism-Europe.",
    },
    {
        "name": "Nederlandse Vereniging voor Autisme (N.V.A.)",
        "address": "Weltevreden 4a, 3731 AL De Bilt, Netherlands",
        "website": "https://www.autisme.nl",
        "type": "advocacy", "services": ["Advocacy", "Information & Support"],
        "description": "National autism association of the Netherlands; full member of Autism-Europe.",
    },
    {
        "name": "Autismeforeningen I Norge (A.I.N.)",
        "address": "Wergelandsveien 1-3, 0167 Oslo, Norway",
        "website": "https://www.autismeforeningen.no",
        "type": "advocacy", "services": ["Advocacy", "Information & Support"],
        "description": "National autism association of Norway; full member of Autism-Europe.",
    },
    {
        "name": "Autism Poland Association",
        "address": "Ul. Ondraszka 3, 02-085 Warszawa, Poland",
        "website": "https://autyzmpolska.org.pl",
        "type": "advocacy", "services": ["Advocacy", "Information & Support"],
        "description": "National autism association of Poland; full member of Autism-Europe.",
    },
    {
        "name": "Federacao Portuguesa De Autismo",
        "address": "Rua Jose Luis Garcia Rodrigues, Bairro Alto da Ajuda, 1300-565 Lisboa, Portugal",
        "website": "https://www.fpda.pt",
        "type": "advocacy", "services": ["Advocacy", "Information & Support"],
        "description": "National autism federation of Portugal; full member of Autism-Europe.",
    },
    {
        "name": "Serbian Society for Autism",
        "address": "Gundulicev venac Street 38, 11000 Belgrade, Serbia",
        "website": "https://www.autizam.org.rs",
        "type": "advocacy", "services": ["Advocacy", "Information & Support"],
        "description": "National autism society of Serbia; full member of Autism-Europe.",
    },
    {
        "name": "Spolocnost na pomoc osobam s autizmom (S.P.O.S.A.)",
        "address": "Namestie 1. maja 1, 810 00 Bratislava, Slovakia",
        "website": "https://www.sposa.sk",
        "type": "advocacy", "services": ["Advocacy", "Information & Support"],
        "description": "National association helping people with autism in Slovakia; full member of Autism-Europe.",
    },
    {
        "name": "Asociacion de padres de ninos y ninas autistas de Bizkaia (APNABI)",
        "address": "Sabino Arana 69, 48012 Bilbao, Spain",
        "website": "http://www.apnabi.org",
        "type": "advocacy", "services": ["Advocacy", "Information & Support"],
        "description": "Autism parents association in Bizkaia, Spain; full member of Autism-Europe.",
    },
    {
        "name": "Autismo Burgos",
        "address": "C/ Valdenunez 8, 09001 Burgos, Spain",
        "website": "https://www.autismoburgos.org",
        "type": "advocacy", "services": ["Advocacy", "Information & Support"],
        "description": "Regional autism association in Burgos, Spain; full member of Autism-Europe.",
    },
    {
        "name": "Autismo-Espana",
        "address": "C/ Garibay 7 3 izq, 28007 Madrid, Spain",
        "website": "https://www.autismo.org.es",
        "type": "advocacy", "services": ["Advocacy", "Information & Support"],
        "description": "National autism confederation of Spain; full member of Autism-Europe.",
    },
    {
        "name": "Federacion Espanola De Autismo (F.E.S.P.A.U.)",
        "address": "C/ Garibay 7 3 Dcha, 28007 Madrid, Spain",
        "website": "https://www.fespau.es",
        "type": "advocacy", "services": ["Advocacy", "Information & Support"],
        "description": "National federation of autism associations in Spain; full member of Autism-Europe.",
    },
    {
        "name": "Gautena",
        "address": "P.O. Box 1000, 20080 San Sebastian, Spain",
        "website": "https://www.gautena.org",
        "type": "advocacy", "services": ["Advocacy", "Information & Support"],
        "description": "Regional autism association in San Sebastian, Spain; full member of Autism-Europe.",
    },
    {
        "name": "Autisme Suisse",
        "address": "Neuengasse 19, 2501 Biel, Switzerland",
        "website": "https://www.autismesuisse.ch",
        "type": "advocacy", "services": ["Advocacy", "Information & Support"],
        "description": "National autism parents association of Switzerland; full member of Autism-Europe.",
    },
    {
        "name": "National Autistic Society (N.A.S.)",
        "address": "393 City Road, London EC1V 1NG, United Kingdom",
        "website": "https://www.nas.org.uk",
        "type": "advocacy", "services": ["Advocacy", "Information & Support"],
        "description": "National autistic society of the United Kingdom; full member of Autism-Europe.",
    },
    {
        "name": "Scottish Autism",
        "address": "Hilton House, Alloa Business Park, Whins Road, Alloa FK10 3SA, Scotland, United Kingdom",
        "website": "https://www.scottishautism.org",
        "type": "advocacy", "services": ["Advocacy", "Information & Support"],
        "description": "National autism organization of Scotland; full member of Autism-Europe.",
    },
    # --- Affiliated/associate members: regional associations ---
    {
        "name": "Autism Today Association",
        "address": "2 Vitosha Street, 1738 Sofia, Bulgaria",
        "website": "https://www.autismtoday-bg.eu",
        "type": "advocacy", "services": ["Advocacy", "Information & Support"],
        "description": "Regional autism association in Bulgaria; affiliated member of Autism-Europe.",
    },
    {
        "name": "Autism Support Famagusta",
        "address": "5341 Ayia Napa, Cyprus",
        "website": "https://www.autismsupportfamagusta.com",
        "type": "general_support", "services": ["Information & Support", "Family Support"],
        "description": "Regional autism support association in Famagusta, Cyprus; affiliated member of Autism-Europe.",
    },
    {
        "name": "Estonian Autism Alliance",
        "address": "Rahu 8, Tartu 50112, Estonia",
        "type": "advocacy", "services": ["Advocacy", "Information & Support"],
        "description": "National autism alliance of Estonia; affiliated member of Autism-Europe.",
    },
    {
        "name": "Union Regionale Autisme-France Poitou-Charentes",
        "address": "12 Rue Joseph Cugnot, 79000 Niort, France",
        "website": "https://www.autisme-poitoucharentes.fr",
        "type": "advocacy", "services": ["Advocacy", "Information & Support"],
        "description": "Regional autism association in Poitou-Charentes, France; affiliated member of Autism-Europe.",
    },
    {
        "name": "Dialogue Autisme",
        "address": "45162 Olivet Cedex, France",
        "website": "https://www.dialogueautisme.com",
        "type": "general_support", "services": ["Information & Support", "Family Support"],
        "description": "Regional autism support association in Olivet, France; affiliated member of Autism-Europe.",
    },
    {
        "name": "The Latvian Autism Association",
        "address": "Terbatas 28-15, LV-1010 Riga, Latvia",
        "website": "https://www.autisms.lv",
        "type": "advocacy", "services": ["Advocacy", "Information & Support"],
        "description": "National autism association of Latvia; affiliated member of Autism-Europe.",
    },
    {
        "name": "Associacao Portuguesa para as Perturbacoes do Desenvolvimento e Autismo (A.P.P.D.A.-Lisboa)",
        "address": "Rua Jose Luis Garcia Rodrigues, Bairro Alto da Ajuda, 1300-565 Lisboa, Portugal",
        "website": "https://www.appda-lisboa.org.pt",
        "type": "advocacy", "services": ["Advocacy", "Information & Support"],
        "description": "Regional autism and development disorders association in Lisbon, Portugal; affiliated member of Autism-Europe.",
    },
    {
        "name": "Zveza NVO za avtizem Slovenije (Association of NGOs for Autism Slovenia)",
        "address": "Ulica Ivanke Uranjek 1, 3310 Zalec, Slovenia",
        "website": "https://www.zveza-avtizem.eu",
        "type": "advocacy", "services": ["Advocacy", "Information & Support"],
        "description": "National association of NGOs for autism in Slovenia; affiliated member of Autism-Europe.",
    },
    {
        "name": "Asperga Center - A Coruna",
        "address": "Avenida de Oza 240, 15006 A Coruna, Spain",
        "website": "https://www.asperga.org",
        "type": "advocacy", "services": ["Advocacy", "Information & Support"],
        "description": "Asperger's/autism association in A Coruna, Spain; affiliated member of Autism-Europe.",
    },
    {
        "name": "Asociacion Navarra de Autismo (ANA)",
        "address": "Monasterio de Urdax 36, 31011 Pamplona, Spain",
        "website": "https://www.autismonavarra.com",
        "type": "advocacy", "services": ["Advocacy", "Information & Support"],
        "description": "Regional autism association in Navarra, Spain; affiliated member of Autism-Europe.",
    },
    {
        "name": "Autismo Galicia",
        "address": "Rua Home Santo de Bonaval 74, 15703 Santiago de Compostela, Spain",
        "website": "https://www.autismogalicia.org",
        "type": "advocacy", "services": ["Advocacy", "Information & Support"],
        "description": "Regional autism association in Galicia, Spain; affiliated member of Autism-Europe.",
    },
    {
        "name": "Fundacio Congost Autisme",
        "address": "Ronda del Carril 75, 08530 La Garriga, Barcelona, Spain",
        "website": "https://www.autisme.com",
        "type": "general_support", "services": ["Information & Support", "Family Support"],
        "description": "Regional autism foundation in Barcelona, Spain; affiliated member of Autism-Europe.",
    },
    {
        "name": "Nuevo Horizonte",
        "address": "Avda de la Comunidad de Madrid s/n, 28230 Las Rozas de Madrid, Spain",
        "website": "https://www.nuevohorizonte.es",
        "type": "general_support", "services": ["Information & Support", "Family Support"],
        "description": "Regional disability/autism support organization near Madrid, Spain; affiliated member of Autism-Europe.",
    },
    {
        "name": "Fundacion Mas Casadevall (FMCA)",
        "address": "17820 Banyoles, Girona, Spain",
        "website": "https://www.mascasadevall.net",
        "type": "general_support", "services": ["Information & Support", "Family Support"],
        "description": "Regional autism foundation in Girona, Spain; affiliated member of Autism-Europe.",
    },
    {
        "name": "Autismo Sevilla",
        "address": "Avda. del Deporte s/n, 41020 Sevilla, Spain",
        "website": "https://www.autismosevilla.org",
        "type": "advocacy", "services": ["Advocacy", "Information & Support"],
        "description": "Regional autism association in Sevilla, Spain; affiliated member of Autism-Europe.",
    },
    {
        "name": "Autisme Suisse Romande",
        "address": "av. de la Chabliere 4, 1004 Lausanne, Switzerland",
        "website": "https://www.autisme.ch",
        "type": "advocacy", "services": ["Advocacy", "Information & Support"],
        "description": "French-speaking regional autism association in Switzerland; affiliated member of Autism-Europe.",
    },
    {
        "name": "Autism Initiatives",
        "address": "Sefton House, Bridle Road, Bootle, Merseyside L30 4XR, United Kingdom",
        "website": "https://www.autisminitiatives.org",
        "type": "general_support", "services": ["Information & Support", "Family Support"],
        "description": "Regional autism support organization in the UK; affiliated member of Autism-Europe.",
    },
    {
        "name": "Autism Northern Ireland (N.I. Autism/PAPA)",
        "address": "Donard, Knockbracken Healthcare Park, Saintfield Road, Belfast BT8 8BH, United Kingdom",
        "website": "https://www.autismni.org",
        "type": "advocacy", "services": ["Advocacy", "Information & Support"],
        "description": "Regional autism association in Northern Ireland; affiliated member of Autism-Europe.",
    },
    {
        "name": "Autism East Midlands",
        "address": "Unit 31 Crags Industrial Estate, Morven Street, Creswell, Worksop, Nottinghamshire S80 4AJ, United Kingdom",
        "website": "https://www.autismeastmidlands.org.uk",
        "type": "general_support", "services": ["Information & Support", "Family Support"],
        "description": "Regional autism support organization in the East Midlands, UK; affiliated member of Autism-Europe.",
    },
    {
        "name": "AT-Autism",
        "address": "20-22 Wenlock Road, London N1 7GU, United Kingdom",
        "website": "https://www.atautism.org",
        "type": "advocacy", "services": ["Advocacy", "Information & Support"],
        "description": "Regional autism training and advocacy organization in the UK; affiliated member of Autism-Europe.",
    },
    {
        "name": "Associazione Nazionale Genitori Soggetti Autistici Lombardia (ANGSA Lombardia)",
        "address": "Via B. Rucellai 36, 20126 Milano, Italy",
        "website": "https://www.angsalombardia.it",
        "type": "advocacy", "services": ["Advocacy", "Information & Support"],
        "description": "Regional association of parents of autistic people in Lombardy, Italy; associate member of Autism-Europe.",
    },
    {
        "name": "Fondazione Oltre Il Labirinto Onlus",
        "address": "Via Botteniga, 31100 Treviso, Italy",
        "website": "https://www.oltrelabirinto.it",
        "type": "general_support", "services": ["Information & Support", "Family Support"],
        "description": "Regional autism foundation in Treviso, Italy; associate member of Autism-Europe.",
    },
    {
        "name": "Associazione Diversamente ODV",
        "address": "Via Caterina Segurana 12, 09134 Cagliari, Italy",
        "website": "https://www.diversamenteonlus.org",
        "type": "general_support", "services": ["Information & Support", "Family Support"],
        "description": "Regional disability/autism support association in Cagliari, Italy; associate member of Autism-Europe.",
    },
    {
        "name": "Mars Foundation (Mars Autistakert Alapitvany)",
        "address": "Jaszai Mari ter 5-6, Budapest, Hungary",
        "website": "https://marsalapitvany.hu",
        "type": "general_support", "services": ["Information & Support", "Family Support"],
        "description": "Regional autism foundation in Budapest, Hungary; associate member of Autism-Europe.",
    },
    {
        "name": "Inspire (The Eden & Razzett Foundation)",
        "address": "Bulebel, Zejtun ZTN 3000, Malta",
        "website": "https://www.inspire.org.mt",
        "type": "general_support", "services": ["Information & Support", "Family Support"],
        "description": "Disability/autism support foundation in Malta; associate member of Autism-Europe.",
    },
    {
        "name": "Fundacja Wspolnota Nadziei (Community of Hope Foundation)",
        "address": "Wieckowice, ul. Ogrodowa 17, 32-082 Bolechowice, Poland",
        "website": "https://www.farma.org.pl",
        "type": "general_support", "services": ["Information & Support", "Family Support"],
        "description": "Regional autism/community foundation in Poland; associate member of Autism-Europe.",
    },
    {
        "name": "Synapsis Foundation",
        "address": "Ul. Ondraszka 3, 02-085 Warszawa, Poland",
        "website": "https://www.synapsis.waw.pl",
        "type": "medical", "services": ["Diagnosis Support", "Therapy"],
        "description": "Regional autism diagnosis and therapy foundation in Warsaw, Poland; associate member of Autism-Europe.",
    },
    {
        "name": "JiM Foundation",
        "address": "Ul. Tatrzanska 105, 93-279 Lodz, Poland",
        "website": "https://www.jim.org",
        "type": "general_support", "services": ["Information & Support", "Family Support"],
        "description": "Regional autism foundation in Lodz, Poland; associate member of Autism-Europe.",
    },
    {
        "name": "HELP AUTISM",
        "address": "Intrarea Graurului nr 9, Sector 3, Bucuresti, Romania",
        "website": "https://www.helpautism.ro",
        "type": "advocacy", "services": ["Advocacy", "Information & Support"],
        "description": "National autism advocacy organization of Romania; associate member of Autism-Europe.",
    },
    {
        "name": "Denizli Autism Association (DAA)",
        "address": "Yenisehir Mah. Ferahevler Sitesi, Merkezefendi/Denizli, Turkey",
        "website": "http://otizmdenizli.org",
        "type": "advocacy", "services": ["Advocacy", "Information & Support"],
        "description": "Regional autism association in Denizli, Turkey; associate member of Autism-Europe.",
    },
    {
        "name": "Tohum Foundation",
        "address": "Cumhuriyet Mah. Abide-i Hurriyet Cad. No: 39, 34380 Sisli-Istanbul, Turkey",
        "website": "http://www.tohumotizm.org.tr",
        "type": "advocacy", "services": ["Advocacy", "Information & Support"],
        "description": "National autism foundation of Turkey; associate member of Autism-Europe.",
    },
    {
        "name": "Child With Future",
        "address": "21/16 Skovorody Str., Kyiv 04070, Ukraine",
        "website": "https://www.cwf.com.ua",
        "type": "general_support", "services": ["Information & Support", "Family Support"],
        "description": "National children's disability/autism support organization of Ukraine; associate member of Autism-Europe.",
    },
    {
        "name": "Association de prefiguration de la Fondation 3A",
        "address": "36 la Feuvrais, 44110 Erbray, France",
        "website": "http://fondation3a.fr",
        "type": "general_support", "services": ["Information & Support", "Family Support"],
        "description": "Regional autism foundation-in-formation in Erbray, France; associate member of Autism-Europe.",
    },
    {
        "name": "E.D.I. Formation",
        "address": "2791 Chemin de Saint Bernard, 06220 Vallauris, France",
        "website": "https://www.ediformation.fr",
        "type": "education", "services": ["Training", "Education"],
        "description": "Regional autism training organization in Vallauris, France; associate member of Autism-Europe.",
    },
    {
        "name": "Union Nationale des Associations de Parents et Amis de Personnes Handicapees Mentales (U.N.A.P.E.I.)",
        "address": "15 Rue Coysevox, 75876 Paris Cedex 18, France",
        "website": "https://www.unapei.org",
        "type": "advocacy", "services": ["Advocacy", "Information & Support"],
        "description": "National union of associations for people with intellectual disabilities in France; associate member of Autism-Europe.",
    },
]


def geocode_query(query):
    params = {"q": query, "format": "json", "limit": 1}
    url = NOMINATIM + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers=HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            results = json.loads(resp.read())
        if results:
            return {"lat": float(results[0]["lat"]), "lng": float(results[0]["lon"])}
    except Exception as e:
        print(f"  geocode failed for {query!r}: {e}")
    return None


def geocode(address):
    coords = geocode_query(address)
    if coords:
        return coords
    time.sleep(1.1)
    # Fall back to city + country -- still an accurate pin, just not street-level
    parts = [p.strip() for p in address.split(",")]
    fallback = ", ".join(parts[-2:]) if len(parts) >= 2 else address
    print(f"  full address failed, retrying with {fallback!r}")
    return geocode_query(fallback)


def main():
    resources = []
    for e in ENTRIES:
        coords = geocode(e["address"])
        time.sleep(1.1)  # Nominatim usage policy: max 1 req/sec
        entry = {
            "name": e["name"],
            "address": e["address"],
            "type": e["type"],
            "source": SOURCE_PDF,
            "services": e["services"],
            "description": e["description"],
        }
        if e.get("website"):
            entry["website"] = e["website"]
        if coords:
            entry["coordinates"] = coords
        else:
            entry["placeless"] = True
        resources.append(entry)
        print(f"  {e['name']}: {'geocoded' if coords else 'NOT geocoded (placeless)'}")

    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(resources, f, indent=2, ensure_ascii=False)

    with_coords = sum(1 for r in resources if r.get("coordinates"))
    print(f"\nWrote {len(resources)} entries to {OUT_PATH}")
    print(f"  {with_coords}/{len(resources)} geocoded")


if __name__ == "__main__":
    main()
