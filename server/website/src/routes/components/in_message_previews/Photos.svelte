<script lang="ts">
    // Props to receive the image URL/blob
    export let src: string;
</script>

<div class="photo-preview-container">
    <!-- Checkerboard background container -->
    <div class="checkerboard-background">
        <!-- Actual image -->
        <img {src} alt="Preview" class="preview-image" />
    </div>
    <!-- Photos icon -->
    <div class="icon_rounded photos"></div>
</div>

<style>
    .photo-preview-container {
        width: 300px;
        height: 200px;
        border-radius: 30px;
        position: relative;
        overflow: hidden;
        box-shadow: 0 4px 8px rgba(0, 0, 0, 0.1);
    }

    .checkerboard-background {
        width: 100%;
        height: 100%;
        background-image: linear-gradient(45deg, #f0f0f0 25%, transparent 25%),
                          linear-gradient(-45deg, #f0f0f0 25%, transparent 25%),
                          linear-gradient(45deg, transparent 75%, #f0f0f0 75%),
                          linear-gradient(-45deg, transparent 75%, #f0f0f0 75%);
        background-size: 20px 20px;
        background-position: 0 0, 0 10px, 10px -10px, -10px 0px;
        background-color: #ffffff;
        display: flex;
        align-items: center;
        justify-content: center;
    }

    .preview-image {
        max-width: 100%;
        max-height: 100%;
        object-fit: contain;
        display: block;
    }
    .icon_rounded{
        position: absolute;
        bottom: 0px;
        left: 0px;
        z-index: 2;
    }
</style>
