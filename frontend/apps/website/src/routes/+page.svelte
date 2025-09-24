<script lang="ts">
    import { MetaTags, getMetaTags } from '@repo/ui';
    
    const meta = getMetaTags('for_all_of_us');
    
    /**
     * Downloads the PDF file by creating a temporary anchor element
     * This ensures the file is downloaded rather than opened in a new tab
     */
    function downloadPDF() {
        console.log('Downloading PDF...');
        
        // Create a temporary anchor element to trigger download
        const link = document.createElement('a');
        link.href = '/slides/openmates_overview_slides.pdf';
        link.download = 'openmates_overview_slides.pdf'; // Set the filename for download
        link.target = '_blank'; // Open in new tab as fallback
        
        // Append to body, click, and remove
        document.body.appendChild(link);
        link.click();
        document.body.removeChild(link);
        
        console.log('PDF download initiated');
    }
</script>

<!-- Render meta tags -->
<MetaTags {...meta} />

<!-- Coming Soon Page -->
<main class="coming-soon-container">
    <div class="content">
        <!-- Main heading -->
        <h1>New website coming soon…</h1>

        <!-- Web App Button -->
        <div class="button-section">
            <!-- Alpha disclaimer -->
            <p>
                Are you a developer or enthusiast?<br>Check out the alpha release of the web app:
            </p>
            <button on:click={() => window.open('https://app.openmates.org', '_blank')}>
                Open web app
            </button>
            
            
        </div>
        
        <!-- PDF Preview Section -->
        <div class="pdf-section">
            <h2>OpenMates Overview</h2>
            <div class="pdf-container">
                <!-- Privacy-focused PDF embedding using object tag -->
                <object 
                    data="/slides/openmates_overview_slides.pdf" 
                    type="application/pdf" 
                    class="pdf-viewer"
                    aria-label="OpenMates Overview Slides PDF">
                    <!-- Fallback content for browsers that don't support PDF embedding -->
                    <div class="pdf-fallback">
                        <p>Your browser doesn't support PDF preview.</p>
                        <button on:click={downloadPDF}>
                            Download PDF
                        </button>
                    </div>
                </object>
            </div>
        </div>
        
        
    </div>
</main>

<style>
    .coming-soon-container {
        min-height: 100vh;
        display: flex;
        align-items: center;
        justify-content: center;
        padding: 2rem;
        font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
    }
    
    .content {
        max-width: 1200px;
        width: 100%;
        text-align: center;
        padding: 3rem;
    }
    
    .pdf-section {
        margin: 3rem 0;
    }
    
    .pdf-container {
        border: 2px solid var(--color-grey-20);
        border-radius: 12px;
        overflow: hidden;
        box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1);
        background: var(--color-grey-10);
    }
    
    .pdf-viewer {
        width: 100%;
        height: 750px;
        border: none;
        display: block;
    }
    
    .pdf-fallback {
        padding: 2rem;
        text-align: center;
        color: var(--color-grey-60);
    }
    
    .button-section {
        margin-top: 3rem;
    }
    
    /* Responsive design */
    @media (max-width: 768px) {
        .coming-soon-container {
            padding: 1rem;
        }
        
        .content {
            padding: 2rem;
        }
        
        
        .pdf-viewer {
            height: 400px;
        }
    }
    
    @media (max-width: 480px) {
        
        .pdf-viewer {
            height: 300px;
        }
    }
</style>
