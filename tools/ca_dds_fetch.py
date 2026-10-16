#!/usr/bin/env python3
"""
California Department of Developmental Services (DDS) ArcGIS layers, keyless JSON with coordinates:

    https://services3.arcgis.com/aogSfRJCHNPulIe6/arcgis/rest/services/<Layer>/FeatureServer/0/query?where=1=1&outFields=*&outSR=4326&f=json

  DDS_RegionalCenters        21  the 21 regional centres -- every California family with a developmental
                                 disability (autism included) enters services through one
  FamilyResourceCenters      45  Early Start family resource centres
  FamilyEmpowermentCenters   35  family empowerment centres
  SAE_CNP_FRCs_Locations     21  LA-area family resource centres (parent regional centre in the description)

Rows are disability_scope "neurodevelopmental" (developmental disabilities: autism, intellectual disability,
cerebral palsy, epilepsy). The translated-name fields are ignored. Writes new_resources_ca_dds.json.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import registry_common as rc  # noqa: E402

BASE = "https://services3.arcgis.com/aogSfRJCHNPulIe6/arcgis/rest/services/{}/FeatureServer/0/query?where=1%3D1&outFields=*&outSR=4326&f=json"
SOURCE = "California Department of Developmental Services (DDS) - official regional centre and family resource centre layers"


def layer(name):
    return [(f["attributes"], f["geometry"]) for f in rc.get_json(BASE.format(name), timeout=60)["features"]]


def main():
    out = []
    for a, g in layer("DDS_RegionalCenters"):
        addr = f"{rc.clean(a['ADDRESS'])}, {rc.clean(a['CITY'])}, CA {a['ZIPCODE']}"
        desc = f"One of California's 21 regional centres for people with developmental disabilities (autism, intellectual disability, cerebral palsy, epilepsy); the entry point to state-funded services. Serves {rc.clean(a['CATCHMENT_AREAS'])}."
        if a.get("EARLY_START_INTAKE"):
            desc += f" Early Start intake: {rc.clean(a['EARLY_START_INTAKE'])}."
        out.append(rc.entry(a["NAME"], SOURCE, "general_support", ["Information & Support", "Case Management", "Early Intervention", "Autism Support"],
                            desc, address=addr, phone=a["PHONE"], website=rc.clean_url(a["WEBSITE"]), lat=g["y"], lng=g["x"],
                            external_id=f"ca-dds:rc:{a['REG_ID']}", scope="neurodevelopmental"))
    for a, g in layer("FamilyResourceCenters"):
        addr = f"{rc.clean(a['FRC_STREET_ADDRESS'])}, {rc.clean(a['FRC_CITY'])}, CA {a['FRC_ZIP_CODE']}"
        out.append(rc.entry(a["FRC_TITLE"], SOURCE, "general_support", ["Information & Support", "Early Intervention"],
                            f"Early Start family resource centre (California DDS), serving {rc.clean(a['FRC_REGIONS_SERVED'])}.",
                            address=addr, phone=a["FRC_PHONE_NUMBER"], website=rc.clean_url(a["FRC_URL"]), lat=g["y"], lng=g["x"],
                            external_id=f"ca-dds:frc:{a['FRC_ID']}", scope="neurodevelopmental"))
    for a, g in layer("FamilyEmpowermentCenters"):
        addr = f"{rc.clean(a['FEC_STREET_ADDRESS'])}, {rc.clean(a['FEC_CITY'])}, CA {a['FEC_ZIP_CODE']}"
        out.append(rc.entry(a["FEC_TITLE"], SOURCE, "general_support", ["Information & Support", "Family Support"],
                            f"Family empowerment centre for families of children with disabilities (California DDS), serving {rc.clean(a['FEC_REGIONS_SERVED'])}.",
                            address=addr, phone=a["FEC_PHONE_NUMBER"], website=rc.clean_url(a["FEC_URL"]), lat=g["y"], lng=g["x"],
                            external_id=f"ca-dds:fec:{a['FEC_ID']}", scope="neurodevelopmental"))
    for a, g in layer("SAE_CNP_FRCs_Locations"):
        addr = f"{rc.clean(a['FRC_STREET_ADDRESS'])}, {rc.clean(a['FRC_CITY'])}, CA {a['FRC_ZIPCODE']}"
        out.append(rc.entry(a["FRC_TITLE"], SOURCE, "general_support", ["Information & Support", "Family Support"],
                            f"Family resource centre of the {rc.clean(a['REGIONAL_CENTER'])} (California DDS).",
                            address=addr, website=rc.clean_url(a["FRC_URL"]), lat=g["y"], lng=g["x"],
                            external_id=f"ca-dds:sae:{a['OBJECTID']}", scope="neurodevelopmental"))
    for e in out:
        assert rc.plausible("US", e["coordinates"]["lat"], e["coordinates"]["lng"]), e["name"]
    res = rc.finalize(os.path.join(rc.REPO, "new_resources_ca_dds.json"), out)
    rc.spot_check(res, 6, fields=("name", "address"))


if __name__ == "__main__":
    main()
