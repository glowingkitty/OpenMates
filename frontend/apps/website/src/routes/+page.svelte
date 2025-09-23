<script lang="ts">
    import { MetaTags, getMetaTags } from '@repo/ui';
    import { onMount } from 'svelte';
    import PdfViewer from 'svelte-pdf';
    
    const meta = getMetaTags('for_all_of_us');
    
    let pdfUrl = '';
    
    onMount(() => {
        // Set the PDF URL to the slides file
        pdfUrl = '/openmates_overview_slides.pdf';
    });
</script>

<!-- Render meta tags -->
<MetaTags {...meta} />

<main class="temp-website">
    <div class="container">
        <div class="content">
            <h1>New website coming soon...</h1>
            
            <div class="pdf-preview">
                {#if pdfUrl}
                    <PdfViewer 
                        src={pdfUrl}
                        width="100%"
                        height="600px"
                        scale="1.0"
                    />
                {/if}
            </div>
            
            <div class="actions">
                <a href="https://app.openmates.org" class="app-button" target="_blank" rel="noopener noreferrer">
                    Open web app
                </a>
                <p class="disclaimer">alpha release. For developers & enthusiasts only.</p>
            </div>
        </div>
    </div>
</main>

<style>
    .temp-website {
        min-height: 100vh;
        display: flex;
        align-items: center;
        justify-content: center;
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        padding: 2rem;
    }
    
    .container {
        max-width: 800px;
        width: 100%;
    }
    
    .content {
        background: white;
        border-radius: 12px;
        padding: 3rem;
        box-shadow: 0 20px 40px rgba(0, 0, 0, 0.1);
        text-align: center;
    }
    
    h1 {
        font-size: 2.5rem;
        color: #333;
        margin-bottom: 2rem;
        font-weight: 600;
    }
    
    .pdf-preview {
        margin: 2rem 0;
        border-radius: 8px;
        overflow: hidden;
        box-shadow: 0 4px 12px rgba(0, 0, 0, 0.1);
    }
    
    .pdf-preview :global(canvas) {
        border-radius: 8px;
    }
    
    .actions {
        margin-top: 2rem;
    }
    
    .app-button {
        display: inline-block;
        background: #667eea;
        color: white;
        padding: 1rem 2rem;
        border-radius: 8px;
        text-decoration: none;
        font-weight: 600;
        font-size: 1.1rem;
        transition: all 0.3s ease;
        box-shadow: 0 4px 12px rgba(102, 126, 234, 0.3);
    }
    
    .app-button:hover {
        background: #5a6fd8;
        transform: translateY(-2px);
        box-shadow: 0 6px 16px rgba(102, 126, 234, 0.4);
    }
    
    .disclaimer {
        margin-top: 1rem;
        color: #666;
        font-size: 0.9rem;
        font-style: italic;
    }
    
    @media (max-width: 768px) {
        .temp-website {
            padding: 1rem;
        }
        
        .content {
            padding: 2rem;
        }
        
        h1 {
            font-size: 2rem;
        }
        
        .pdf-preview {
            height: 400px;
        }
    }
</style>
