<script lang="ts">
    // Props for configuring the separator's appearance
    export let reverse_direction: boolean = false;
</script>

<div class="large-separator" style={reverse_direction ? "rotate: 180deg" : ""}>
    <div class="separator-content"></div>
</div>
