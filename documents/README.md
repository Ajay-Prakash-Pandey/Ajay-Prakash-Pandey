# Resume Download Feature

## Instructions

1. **Add Your Resume File**
   - Place your resume file (PDF format preferred) in this `documents` folder
   - Name it `resume.pdf` or `Resume.pdf`
   - The download route will automatically serve it

2. **Supported Formats**
   - PDF (recommended) - application/pdf
   - DOCX - application/vnd.openxmlformats-officedocument.wordprocessingml.document
   - DOC - application/msword

3. **How It Works**
   - Users can click the "Download Resume" button on the portfolio
   - The file will be downloaded with filename: `Resume.pdf`
   - Route: `/download-resume`

## Setup Steps

1. Create or export your resume as PDF
2. Save it to this folder as `resume.pdf`
3. Restart the Flask application
4. The download button will now work automatically!

## Example Resume Content

Your resume should include:
- Professional Summary
- Work Experience
- Skills
- Education
- Certifications
- Projects
- Contact Information

## Security Note

Only files in the `documents` folder can be downloaded. The application validates file existence before serving.
