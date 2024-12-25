<script lang="ts">
    import { externalLinks } from '$lib/config/links';
    import MetaTags from '../../components/MetaTags.svelte';
    import { getMetaTags } from '$lib/config/meta';

    const meta = getMetaTags('legalTerms');

    // Get current build date and format it
    const buildDate = new Date().toLocaleDateString('de-DE', {
        year: 'numeric',
        month: 'long',
        day: 'numeric'
    });
</script>

<MetaTags {...meta} />

<div class="legal-container">
    <h1>Terms and Conditions</h1>
    
    <p class="last-updated">Last Updated: {buildDate}</p>

    <section>
        <h2>1. Agreement to Terms</h2>
        <p>By accessing and using the OpenMates website ("Website"), you accept and agree to be bound by these Terms and Conditions. If you disagree with any part of these terms, you may not access the Website.</p>
    </section>

    <section>
        <h2>2. About OpenMates</h2>
        <p>OpenMates is currently a closed-source software project during its initial development phase. This temporary closed-source status is maintained to ensure security and stability during the early development and beta testing phases. The project will transition to open-source after the completion of initial beta testing and security reviews.</p>
        <p>This Website serves as an informational platform about the OpenMates project and its development progress.</p>
    </section>

    <section>
        <h2>3. Intellectual Property Rights</h2>
        <p>The OpenMates name, logo, and all related content on this Website are the intellectual property of the website owner (see <a href="/legal/imprint">Imprint</a>) and are protected by applicable copyright and trademark laws.</p>
        <p>Once the project transitions to open-source, specific licensing terms will be provided separately through appropriate open-source documentation.</p>
    </section>

    <section>
        <h2>4. Use License</h2>
        <p>Permission is granted to temporarily access the materials on our Website for personal, non-commercial informational purposes only. This is the grant of a license, not a transfer of title, and under this license you may not:</p>
        <ul>
            <li>Modify or copy the materials</li>
            <li>Use the materials for any commercial purpose</li>
            <li>Attempt to reverse engineer any software contained on the Website</li>
            <li>Remove any copyright or other proprietary notations from the materials</li>
        </ul>
    </section>

    <section>
        <h2>5. Discord Community</h2>
        <p>Access to our Discord community is provided as a complementary service. When joining our Discord community, you agree to:</p>
        <ul>
            <li>Comply with Discord's Terms of Service and Community Guidelines</li>
            <li>Be at least 16 years old or have parental consent</li>
            <li>Behave respectfully towards other community members</li>
            <li>Not share inappropriate, illegal, or harmful content</li>
        </ul>
    </section>

    <section>
        <h2>6. Disclaimer</h2>
        <p>The materials and information on this Website are provided 'as is' and without warranties of any kind. We do not guarantee the accuracy, completeness, or usefulness of any information on this Website. Any reliance you place on such information is strictly at your own risk.</p>
    </section>

    <section>
        <h2>7. Limitations</h2>
        <p>To the fullest extent permitted by law, the website owner shall not be liable for any direct, indirect, incidental, consequential, or special damages arising out of or in any way connected with:</p>
        <ul>
            <li>The use or inability to use this Website</li>
            <li>The information provided on this Website</li>
            <li>Any technical issues or interruptions</li>
        </ul>
    </section>

    <section>
        <h2>8. Governing Law</h2>
        <p>These terms and conditions are governed by and construed in accordance with the laws of the Federal Republic of Germany. For details about the responsible jurisdiction and contact information, please refer to our <a href="/legal/imprint">Imprint</a>.</p>
    </section>

    <section>
        <h2>9. Contact Information</h2>
        <p>For questions about these Terms:</p>
        <p>Email: <a href="{externalLinks.email}">{externalLinks.email.replace('mailto:', '')}</a></p>
    </section>
</div>

<style>
    .legal-container {
        max-width: 800px;
        margin: 2rem auto;
        padding: 0 1rem;
    }

    section {
        margin: 2rem 0;
    }

    h1 {
        font-size: 2rem;
        margin-bottom: 2rem;
    }

    h2 {
        font-size: 1.5rem;
        margin: 1.5rem 0 1rem;
    }

    .last-updated {
        font-style: italic;
        color: #666;
        margin-bottom: 2rem;
    }
</style> 