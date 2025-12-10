import streamlit as st
import requests
import json
from uuid import uuid4

API_BASE_URL = "http://localhost:8000/"  # Adjust if deployed elsewhere

st.title("NAMASTE Terminology API Explorer")

tabs = st.tabs([
    "Welcome",
    "CodeSystem Namaste",
    "ConceptMap Namaste-TM2",
    "ValueSet Expand",
    "ConceptMap Translate",
    "Biomed Lookup",
    "Sync WHO Data",
    "Upload FHIR Bundle"
])

with tabs[0]:
    st.header("Welcome")
    st.write("Welcome to the NAMASTE Terminology API 👋")
    st.write("Use the tabs above to explore the API features.")

with tabs[1]:
    st.header("CodeSystem Namaste")
    version = st.text_input("Version (_history) (optional)")
    if st.button("Get CodeSystem"):
        params = {}
        if version:
            params["_history"] = version
        try:
            r = requests.get(f"{API_BASE_URL}/CodeSystem/namaste", params=params)
            r.raise_for_status()
            cs = r.json()
            st.json(cs)
        except Exception as e:
            st.error(f"Error fetching CodeSystem: {e}")

with tabs[2]:
    st.header("ConceptMap Namaste-TM2")
    version = st.text_input("Version (_history) (optional)", key="cm_version")
    if st.button("Get ConceptMap"):
        params = {}
        if version:
            params["_history"] = version
        try:
            r = requests.get(f"{API_BASE_URL}/ConceptMap/namaste-tm2", params=params)
            r.raise_for_status()
            cm = r.json()
            st.json(cm)
        except Exception as e:
            st.error(f"Error fetching ConceptMap: {e}")

with tabs[3]:
    st.header("ValueSet Expand (Autocomplete)")
    filter_text = st.text_input("Filter (min 3 characters)")
    if st.button("Expand") and len(filter_text) >= 3:
        try:
            r = requests.get(f"{API_BASE_URL}/ValueSet/namaste/$expand", params={"filter": filter_text})
            r.raise_for_status()
            expansion = r.json().get("expansion", [])
            if not expansion:
                st.info("No results found")
            else:
                for item in expansion:
                    st.write(f"**Code:** {item['code']}")
                    st.write(f"Display: {item['display']}")
                    ext = item.get("extension", [])
                    for e in ext:
                        st.write(f"- {e['url']}: {e.get('valueCode', e.get('valueDecimal'))}")
                    st.markdown("---")
        except Exception as e:
            st.error(f"Error fetching expansion: {e}")

with tabs[4]:
    st.header("ConceptMap Translate")
    code = st.text_input("Code")
    system = st.selectbox("From system", options=["namaste", "tm2"])
    targetsystem = st.selectbox("To system", options=["tm2", "namaste"])
    if st.button("Translate"):
        if not code:
            st.error("Please enter a code")
        elif system == targetsystem:
            st.error("Source and target systems must differ")
        else:
            try:
                payload = {"code": code, "system": system, "targetsystem": targetsystem}
                r = requests.post(f"{API_BASE_URL}/ConceptMap/$translate", json=payload)
                r.raise_for_status()
                result = r.json()
                st.success(f"Match found: {result}")
            except requests.HTTPError as he:
                if he.response.status_code == 404:
                    st.warning("No mapping found")
                else:
                    st.error(f"HTTP error: {he}")
            except Exception as e:
                st.error(f"Error translating: {e}")

with tabs[5]:
    st.header("Biomed Code Lookup")
    code = st.text_input("Code to lookup", key="biomed_code")
    if st.button("Lookup"):
        if not code:
            st.error("Please enter a code")
        else:
            try:
                r = requests.get(f"{API_BASE_URL}/CodeSystem/biomed/$lookup", params={"code": code})
                r.raise_for_status()
                data = r.json()
                st.write(f"**Code:** {data.get('code')}")
                st.write(f"**Display:** {data.get('display')}")
                st.write(f"**Definition:** {data.get('definition')}")
            except requests.HTTPError as he:
                if he.response.status_code == 404:
                    st.warning("Code not found")
                else:
                    st.error(f"HTTP error: {he}")
            except Exception as e:
                st.error(f"Error looking up code: {e}")

with tabs[6]:
    st.header("Sync WHO Data")
    chapter = st.text_input("Chapter code (e.g., 26 for TM2)", value="26")
    if st.button("Sync Data"):
        try:
            r = requests.post(f"{API_BASE_URL}/sync", params={"chapter": chapter})
            r.raise_for_status()
            result = r.json()
            st.success(f"Sync status: {result.get('status')}, Count: {result.get('count')}")
        except Exception as e:
            st.error(f"Error syncing data: {e}")

with tabs[7]:
    st.header("Record Disorders")
    st.subheader("Search and Select Disorders to Submit as FHIR Bundle")

    # Initialize session state to store selected disorders
    if "selected_disorders" not in st.session_state:
        st.session_state.selected_disorders = []

    # Autocomplete search for disorders
    st.write("Type disorder name to search:")
    filter_text = st.text_input("Enter disorder name (min 3 characters)", key="disorder_search")
    if filter_text and len(filter_text) >= 3:
        try:
            r = requests.get(f"{API_BASE_URL}/ValueSet/namaste/$expand", params={"filter": filter_text})
            r.raise_for_status()
            expansion = r.json().get("expansion", [])
            if not expansion:
                st.info("No disorders found")
            else:
                # Create a list of display strings for selection
                disorder_options = [f"{item['display']} (Code: {item['code']})" for item in expansion]
                selected_options = st.multiselect("Select disorders", options=disorder_options)
                if st.button("Add Selected Disorders"):
                    for selected_option in selected_options:
                        # Extract code and display from selected option
                        selected_code = selected_option.split(" (Code: ")[1].rstrip(")")
                        selected_display = selected_option.split(" (Code: ")[0]
                        # Check if already added to avoid duplicates
                        if selected_code not in [d['code'] for d in st.session_state.selected_disorders]:
                            # Translate to TM2 code
                            tm2_code = ""
                            tm2_display = ""
                            tm2_definition = ""
                            try:
                                r_translate = requests.post(f"{API_BASE_URL}/ConceptMap/$translate", json={
                                    "code": selected_code,
                                    "system": "namaste",
                                    "targetsystem": "tm2"
                                })
                                r_translate.raise_for_status()
                                result = r_translate.json()
                                tm2_code = result.get("match", [{}])[0].get("concept", {}).get("code", "")
                            except Exception:
                                st.warning(f"No TM2 mapping found for {selected_code}")
                            
                            # Fetch NAMASTE details from CodeSystem
                            namaste_short = selected_display
                            namaste_long = ""
                            index_term = selected_display  # Assume IndexTerm is the display; adjust if diacritical is needed
                            try:
                                r_cs = requests.get(f"{API_BASE_URL}/CodeSystem/namaste")
                                r_cs.raise_for_status()
                                cs = r_cs.json()
                                concepts = cs.get("concept", [])
                                concept = next((c for c in concepts if c.get("code") == selected_code), None)
                                if concept:
                                    namaste_short = concept.get("display", selected_display)
                                    namaste_long = concept.get("definition", "")
                                    # If IndexTerm is a property, add here: index_term = concept.get("property_index_term", selected_display)
                            except Exception as e:
                                st.warning(f"Could not fetch NAMASTE details: {e}")
                            
                            # Fetch TM2 details if tm2_code exists
                            if tm2_code:
                                try:
                                    r_lookup = requests.get(f"{API_BASE_URL}/CodeSystem/biomed/$lookup", params={"code": tm2_code})
                                    r_lookup.raise_for_status()
                                    data = r_lookup.json()
                                    tm2_display = data.get("display", "")
                                    tm2_definition = data.get("definition", "")
                                except Exception:
                                    st.warning(f"Could not fetch TM2 details for {tm2_code}")
                            
                            # Add to session state
                            st.session_state.selected_disorders.append({
                                "code": selected_code,
                                "display": selected_display,
                                "tm2_code": tm2_code,
                                "tm2_display": tm2_display,
                                "tm2_definition": tm2_definition,
                                "namaste_short": namaste_short,
                                "namaste_long": namaste_long,
                                "index_term": index_term
                            })
                            st.success(f"Added {selected_display}")
                        else:
                            st.info(f"{selected_display} already added")
        except Exception as e:
            st.error(f"Error fetching disorders: {e}")

    # Display selected disorders
    st.subheader("Selected Disorders")
    to_remove = None
    for idx, d in enumerate(st.session_state.selected_disorders):
        st.write(f"{d['display']} (NAMC_CODE: {d['code']}, TM2 Code: {d['tm2_code']}, IndexTerm: {d['index_term']}, Short Definition: {d['namaste_short']}, Long Definition: {d['namaste_long']})")
        if st.button("Remove", key=f"remove_{idx}"):
            to_remove = idx
    if to_remove is not None:
        del st.session_state.selected_disorders[to_remove]
        st.rerun()

    # Submit button to create and send bundle
    if st.button("Submit") and st.session_state.selected_disorders:
        bundle = {
            "resourceType": "Bundle",
            "type": "collection",
            "entry": []
        }
        for d in st.session_state.selected_disorders:
            condition = {
                "resourceType": "Condition",
                "id": str(uuid4()),
                "code": {
                    "coding": [
                        {
                            "system": "http://example.org/fhir/CodeSystem/namaste",
                            "code": d["code"],
                            "display": d["display"]
                        }
                    ]
                },
                "extension": []
            }
            if d["tm2_code"]:
                condition["code"]["coding"].append({
                    "system": "http://who.int/icd11/tm2",
                    "code": d["tm2_code"],
                    "display": d["tm2_display"]
                })
            # Add extensions for additional fields
            if d["index_term"]:
                condition["extension"].append({
                    "url": "http://example.org/fhir/extension/index-term",
                    "valueString": d["index_term"]
                })
            if d["namaste_short"]:
                condition["extension"].append({
                    "url": "http://example.org/fhir/extension/short-definition",
                    "valueString": d["namaste_short"]
                })
            if d["namaste_long"]:
                condition["extension"].append({
                    "url": "http://example.org/fhir/extension/long-definition",
                    "valueString": d["namaste_long"]
                })
            if d["tm2_definition"]:
                condition["extension"].append({
                    "url": "http://example.org/fhir/extension/tm2-definition",
                    "valueString": d["tm2_definition"]
                })
            bundle["entry"].append({
                "resource": condition
            })

        # Send to /Bundle endpoint, which handles Supabase upload
        try:
            r = requests.post(f"{API_BASE_URL}/Bundle", json=bundle)
            r.raise_for_status()
            st.success("Disorders submitted as FHIR Bundle and sent to Supabase successfully")
            st.json(r.json())
            # Clear selections after success
            st.session_state.selected_disorders = []
        except requests.HTTPError as he:
            st.error(f"HTTP error: {he.response.text}")
        except Exception as e:
            st.error(f"Error submitting bundle: {e}")