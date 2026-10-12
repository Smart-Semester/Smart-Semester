### Summary of Changes                                                                                        
                                                                                                                
  The first syllabus-ingest milestone has been implemented. The pipeline targets the canonical starting point   
  https://hb2504.txst.edu/browsecourses.html#CS https://hb2504.txst.edu/browsecourses.html#CS, extracting       
  syllabus records specifically for Computer Science courses without altering existing course tables or frontend
  code.                                                                                                         
  ──────                                                                                                        
  ### Files Changed / Added                                                                                     
                                                                                                                
   File                    │ Purpose
  ─────────────────────────┼────────────────────────────────────────────────────────────────────────────────────
   02-syllabi.sql          │ Idempotent migration creating catalog.syllabi (with indexes on course_code and
                           │ semester_code).
   models.py               │ Data contracts: SyllabusRecord and ValidationResult.
   fetcher.py              │ Client for https://api.hb2504.txst.edu/py/ with rate-limiting, user agent headers,
                           │ and semester decoder semester_to_label.
   parser.py               │ Pure normalization logic parse_classes_into_records converting raw JSON into typed
                           │ records.
   validator.py            │ Batch validator validate_batch ensuring required fields exist and detecting
                           │ duplicates.
   loader.py               │ Database writer load_records using atomic transactions and ON CONFLICT
                           │ (source_url) DO UPDATE.
   cli.py                  │ CLI entry-point supporting dry-run previews, optional --apply, rate-limiting, and 
                           │ --max-semesters.
   test_syllabus_ingest.py │ 31 offline unit/integration tests running against mock JSON fixtures.
   README.md               │ Pipeline usage, architecture overview, and migration guides.
  ──────                                                                                                        
  ### How the Data-Ingest Workflow Works                                                                        
                                                                                                                
  1. Discovery & Inspection:                                                                                    
      • The starting page https://hb2504.txst.edu/browsecourses.html#CS uses client-side JavaScript (buildjs.py)
      to dynamically pull course and syllabus data via REST JSON endpoints hosted on https://api.hb2504.txst.   
      edu/py/.                                                                                                  
      • Before fetching, https://hb2504.txst.edu/robots.txt was inspected (returns 404, no robots restrictions).
      The crawler respects rate limits with a default 0.25s delay between requests and sets a descriptive User- 
      Agent.                                                                                                    
  2. Ingest Steps:                                                                                              
      • Step 1 (Fetch): Queries getcoursesfordepartment.py?department=CS (yielding 37 CS courses), then queries 
      getcoursedetails.py for semester codes and getclassesforcourse.py for sections. Instructor details are    
      cached via getinstructordetails.py.                                                                       
      • Step 2 (Parse & Normalize): Encoded semester codes (e.g., 202510) are converted to human-readable terms 
      (Fall 2024). Each section is extracted into a SyllabusRecord with its unique download URL https://api.    
      hb2504.txst.edu/py/getsyllabus.py?class=<index_num>.                                                      
      • Step 3 (Validate): Verifies required fields (course_code, course_name, section, semester, source_url),  
      flags missing fields or duplicate entries, and halts writes if errors exist.                              
      • Step 4 (Preview or Load): Defaults to an offline/read-only console preview. When --apply is supplied, it
      executes within a single database transaction using ON CONFLICT (source_url) DO UPDATE to ensure safe,    
      repeatable re-runs.                                                                                       
                                                                                                                
  ──────                                                                                                        
  ### Commands to Run                                                                                           
                                                                                                                
  #### 1. Run Offline Tests                                                                                     
                                                                                                                
    python3 -m pytest ingest/syllabus/tests/test_syllabus_ingest.py -v                                          
                                                                                                                
  (All 31 tests passed in ~0.05s)                                                                               
                                                                                                                
  #### 2. Dry-Run Preview (Live Site Discovery)                                                                 
                                                                                                                
    # Preview 1 semester per course (faster verification)                                                       
    python3 -m ingest.syllabus.cli --max-semesters 1                                                            
                                                                                                                
    # Or preview all available historical semesters across all CS courses                                       
    python3 -m ingest.syllabus.cli                                                                              
                                                                                                                
  #### 3. Database Migration & Apply                                                                            
                                                                                                                
  Because Docker entrypoint scripts in init-db/ only execute when a volume is first created, run the migration  
  manually if an existing database volume already exists:                                                       
                                                                                                                
    # Apply migration to running container                                                                      
    docker exec -i smart_semester_db psql -U postgres -d smart_semester < init-db/02-syllabi.sql                
                                                                                                                
    # Run importer in apply mode                                                                                
    DATABASE_URL="postgresql://postgres:postgrespassword@localhost:5432/smart_semester" \                       
      python3 -m ingest.syllabus.cli --apply --max-semesters 1                                                  
  ──────                                                                                                        
  ### Verified Live Run Results                                                                                 
                                                                                                                
  The live dry-run was executed against https://hb2504.txst.edu/browsecourses.html#CS:                          
                                                                                                                
  • Discovered: 37 CS courses                                                                                   
  • Syllabus entries found (for 1 semester/course sample): 95 class section entries                             
  • Validation: 95 valid, 0 errors, 0 fetch errors                                                              
  ──────                                                                                                        
  ### Extraction Limitations & Observations                                                                     
                                                                                                                
  • Document Text Extraction: The syllabus documents linked by the portal (getsyllabus.py?class=...) are binary 
  PDFs (Content-Type: application/pdf). To avoid heavy dependencies at this initial milestone, the pipeline     
  captures the download URL, section metadata, syllabus presence flag, and original format. Text parsing (e.g., 
  via pdfminer or OCR) can be added as an asynchronous enrichment step.                                         
  • Missing Syllabi: Certain sections in the portal have syllabus: false (no syllabus uploaded yet for that     
  semester/section). These records are preserved with has_syllabus = False rather than skipped or fabricated.  