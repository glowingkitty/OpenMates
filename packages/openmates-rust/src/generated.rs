//! Generated reviewed App namespaces. Regenerate with scripts/generate_rust_sdk_apps.py.
use crate::{error::Result, sdk::OpenMates};
use serde_json::Value;
/// Reviewed public metadata embedded at build time; no runtime filesystem access.
pub fn app_skill_metadata() -> Value {
    serde_json::from_str(include_str!("generated/metadata.json")).expect("generated SDK metadata")
}
#[derive(Clone, Copy)]
pub struct AppSkills<'a> {
    sdk: &'a OpenMates,
}
impl<'a> AppSkills<'a> {
    pub(crate) fn new(sdk: &'a OpenMates) -> Self {
        Self { sdk }
    }
    pub fn ai(&self) -> AiSkills<'a> {
        AiSkills { sdk: self.sdk }
    }
    pub fn audio(&self) -> AudioSkills<'a> {
        AudioSkills { sdk: self.sdk }
    }
    pub fn books(&self) -> BooksSkills<'a> {
        BooksSkills { sdk: self.sdk }
    }
    pub fn business(&self) -> BusinessSkills<'a> {
        BusinessSkills { sdk: self.sdk }
    }
    pub fn code(&self) -> CodeSkills<'a> {
        CodeSkills { sdk: self.sdk }
    }
    pub fn design(&self) -> DesignSkills<'a> {
        DesignSkills { sdk: self.sdk }
    }
    pub fn electronics(&self) -> ElectronicsSkills<'a> {
        ElectronicsSkills { sdk: self.sdk }
    }
    pub fn events(&self) -> EventsSkills<'a> {
        EventsSkills { sdk: self.sdk }
    }
    pub fn fitness(&self) -> FitnessSkills<'a> {
        FitnessSkills { sdk: self.sdk }
    }
    pub fn health(&self) -> HealthSkills<'a> {
        HealthSkills { sdk: self.sdk }
    }
    pub fn home(&self) -> HomeSkills<'a> {
        HomeSkills { sdk: self.sdk }
    }
    pub fn hosting(&self) -> HostingSkills<'a> {
        HostingSkills { sdk: self.sdk }
    }
    pub fn images(&self) -> ImagesSkills<'a> {
        ImagesSkills { sdk: self.sdk }
    }
    pub fn jobs(&self) -> JobsSkills<'a> {
        JobsSkills { sdk: self.sdk }
    }
    pub fn mail(&self) -> MailSkills<'a> {
        MailSkills { sdk: self.sdk }
    }
    pub fn maps(&self) -> MapsSkills<'a> {
        MapsSkills { sdk: self.sdk }
    }
    pub fn math(&self) -> MathSkills<'a> {
        MathSkills { sdk: self.sdk }
    }
    pub fn models3d(&self) -> Models3DSkills<'a> {
        Models3DSkills { sdk: self.sdk }
    }
    pub fn music(&self) -> MusicSkills<'a> {
        MusicSkills { sdk: self.sdk }
    }
    pub fn news(&self) -> NewsSkills<'a> {
        NewsSkills { sdk: self.sdk }
    }
    pub fn nutrition(&self) -> NutritionSkills<'a> {
        NutritionSkills { sdk: self.sdk }
    }
    pub fn openmates(&self) -> OpenmatesSkills<'a> {
        OpenmatesSkills { sdk: self.sdk }
    }
    pub fn pdf(&self) -> PdfSkills<'a> {
        PdfSkills { sdk: self.sdk }
    }
    pub fn plans(&self) -> PlansSkills<'a> {
        PlansSkills { sdk: self.sdk }
    }
    pub fn projects(&self) -> ProjectsSkills<'a> {
        ProjectsSkills { sdk: self.sdk }
    }
    pub fn reminder(&self) -> ReminderSkills<'a> {
        ReminderSkills { sdk: self.sdk }
    }
    pub fn shopping(&self) -> ShoppingSkills<'a> {
        ShoppingSkills { sdk: self.sdk }
    }
    pub fn social_media(&self) -> SocialMediaSkills<'a> {
        SocialMediaSkills { sdk: self.sdk }
    }
    pub fn tasks(&self) -> TasksSkills<'a> {
        TasksSkills { sdk: self.sdk }
    }
    pub fn travel(&self) -> TravelSkills<'a> {
        TravelSkills { sdk: self.sdk }
    }
    pub fn videos(&self) -> VideosSkills<'a> {
        VideosSkills { sdk: self.sdk }
    }
    pub fn weather(&self) -> WeatherSkills<'a> {
        WeatherSkills { sdk: self.sdk }
    }
    pub fn web(&self) -> WebSkills<'a> {
        WebSkills { sdk: self.sdk }
    }
    pub fn workflows(&self) -> WorkflowsSkills<'a> {
        WorkflowsSkills { sdk: self.sdk }
    }
}
#[derive(Clone, Copy)]
pub struct AiSkills<'a> {
    sdk: &'a OpenMates,
}
impl AiSkills<'_> {
    pub async fn decide(&self, input: Value) -> Result<Value> {
        self.sdk.run_skill("ai", "decide", input).await
    }
    pub async fn ask(&self, input: Value) -> Result<Value> {
        self.sdk.run_skill("ai", "ask", input).await
    }
}
#[derive(Clone, Copy)]
pub struct AudioSkills<'a> {
    sdk: &'a OpenMates,
}
impl AudioSkills<'_> {
    pub async fn generate(&self, input: Value) -> Result<Value> {
        self.sdk.run_skill("audio", "generate", input).await
    }
    pub async fn speak(&self, input: Value) -> Result<Value> {
        self.sdk.run_skill("audio", "speak", input).await
    }
}
#[derive(Clone, Copy)]
pub struct BooksSkills<'a> {
    sdk: &'a OpenMates,
}
impl BooksSkills<'_> {
    pub async fn translate(&self, input: Value) -> Result<Value> {
        self.sdk.run_skill("books", "translate", input).await
    }
}
#[derive(Clone, Copy)]
pub struct BusinessSkills<'a> {
    sdk: &'a OpenMates,
}
impl BusinessSkills<'_> {
    pub async fn search_trademarks(&self, input: Value) -> Result<Value> {
        self.sdk
            .run_skill("business", "search_trademarks", input)
            .await
    }
    pub async fn company_financials(&self, input: Value) -> Result<Value> {
        self.sdk
            .run_skill("business", "company_financials", input)
            .await
    }
}
#[derive(Clone, Copy)]
pub struct CodeSkills<'a> {
    sdk: &'a OpenMates,
}
impl CodeSkills<'_> {
    pub async fn search_repos(&self, input: Value) -> Result<Value> {
        self.sdk.run_skill("code", "search_repos", input).await
    }
    pub async fn get_docs(&self, input: Value) -> Result<Value> {
        self.sdk.run_skill("code", "get_docs", input).await
    }
    pub async fn run(&self, input: Value) -> Result<Value> {
        self.sdk.run_skill("code", "run", input).await
    }
    pub async fn image_to_html(&self, input: Value) -> Result<Value> {
        self.sdk.run_skill("code", "image_to_html", input).await
    }
    pub async fn clean_repo(&self, input: Value) -> Result<Value> {
        self.sdk.run_skill("code", "clean_repo", input).await
    }
    pub async fn get_issues(&self, input: Value) -> Result<Value> {
        self.sdk.run_skill("code", "get_issues", input).await
    }
    pub async fn add_issue(&self, input: Value) -> Result<Value> {
        self.sdk.run_skill("code", "add_issue", input).await
    }
    pub async fn remove_secrets(&self, input: Value) -> Result<Value> {
        self.sdk.run_skill("code", "remove_secrets", input).await
    }
    pub async fn get_project_overview(&self, input: Value) -> Result<Value> {
        self.sdk
            .run_skill("code", "get_project_overview", input)
            .await
    }
}
#[derive(Clone, Copy)]
pub struct DesignSkills<'a> {
    sdk: &'a OpenMates,
}
impl DesignSkills<'_> {
    pub async fn search_icons(&self, input: Value) -> Result<Value> {
        self.sdk.run_skill("design", "search_icons", input).await
    }
}
#[derive(Clone, Copy)]
pub struct ElectronicsSkills<'a> {
    sdk: &'a OpenMates,
}
impl ElectronicsSkills<'_> {
    pub async fn search_components(&self, input: Value) -> Result<Value> {
        self.sdk
            .run_skill("electronics", "search_components", input)
            .await
    }
}
#[derive(Clone, Copy)]
pub struct EventsSkills<'a> {
    sdk: &'a OpenMates,
}
impl EventsSkills<'_> {
    pub async fn search(&self, input: Value) -> Result<Value> {
        self.sdk.run_skill("events", "search", input).await
    }
}
#[derive(Clone, Copy)]
pub struct FitnessSkills<'a> {
    sdk: &'a OpenMates,
}
impl FitnessSkills<'_> {
    pub async fn search_locations(&self, input: Value) -> Result<Value> {
        self.sdk
            .run_skill("fitness", "search_locations", input)
            .await
    }
    pub async fn search_classes(&self, input: Value) -> Result<Value> {
        self.sdk.run_skill("fitness", "search_classes", input).await
    }
}
#[derive(Clone, Copy)]
pub struct HealthSkills<'a> {
    sdk: &'a OpenMates,
}
impl HealthSkills<'_> {
    pub async fn search_appointments(&self, input: Value) -> Result<Value> {
        self.sdk
            .run_skill("health", "search_appointments", input)
            .await
    }
}
#[derive(Clone, Copy)]
pub struct HomeSkills<'a> {
    sdk: &'a OpenMates,
}
impl HomeSkills<'_> {
    pub async fn search(&self, input: Value) -> Result<Value> {
        self.sdk.run_skill("home", "search", input).await
    }
}
#[derive(Clone, Copy)]
pub struct HostingSkills<'a> {
    sdk: &'a OpenMates,
}
impl HostingSkills<'_> {
    pub async fn search_domains(&self, input: Value) -> Result<Value> {
        self.sdk.run_skill("hosting", "search_domains", input).await
    }
}
#[derive(Clone, Copy)]
pub struct ImagesSkills<'a> {
    sdk: &'a OpenMates,
}
impl ImagesSkills<'_> {
    pub async fn generate(&self, input: Value) -> Result<Value> {
        self.sdk.run_skill("images", "generate", input).await
    }
    pub async fn generate_draft(&self, input: Value) -> Result<Value> {
        self.sdk.run_skill("images", "generate_draft", input).await
    }
}
#[derive(Clone, Copy)]
pub struct JobsSkills<'a> {
    sdk: &'a OpenMates,
}
impl JobsSkills<'_> {
    pub async fn search(&self, input: Value) -> Result<Value> {
        self.sdk.run_skill("jobs", "search", input).await
    }
}
#[derive(Clone, Copy)]
pub struct MailSkills<'a> {
    sdk: &'a OpenMates,
}
impl MailSkills<'_> {
    pub async fn search(&self, input: Value) -> Result<Value> {
        self.sdk.run_skill("mail", "search", input).await
    }
}
#[derive(Clone, Copy)]
pub struct MapsSkills<'a> {
    sdk: &'a OpenMates,
}
impl MapsSkills<'_> {
    pub async fn search(&self, input: Value) -> Result<Value> {
        self.sdk.run_skill("maps", "search", input).await
    }
}
#[derive(Clone, Copy)]
pub struct MathSkills<'a> {
    sdk: &'a OpenMates,
}
impl MathSkills<'_> {
    pub async fn calculate(&self, input: Value) -> Result<Value> {
        self.sdk.run_skill("math", "calculate", input).await
    }
}
#[derive(Clone, Copy)]
pub struct Models3DSkills<'a> {
    sdk: &'a OpenMates,
}
impl Models3DSkills<'_> {
    pub async fn search(&self, input: Value) -> Result<Value> {
        self.sdk.run_skill("models3d", "search", input).await
    }
}
#[derive(Clone, Copy)]
pub struct MusicSkills<'a> {
    sdk: &'a OpenMates,
}
impl MusicSkills<'_> {
    pub async fn generate(&self, input: Value) -> Result<Value> {
        self.sdk.run_skill("music", "generate", input).await
    }
}
#[derive(Clone, Copy)]
pub struct NewsSkills<'a> {
    sdk: &'a OpenMates,
}
impl NewsSkills<'_> {
    pub async fn search(&self, input: Value) -> Result<Value> {
        self.sdk.run_skill("news", "search", input).await
    }
}
#[derive(Clone, Copy)]
pub struct NutritionSkills<'a> {
    sdk: &'a OpenMates,
}
impl NutritionSkills<'_> {
    pub async fn search_recipes(&self, input: Value) -> Result<Value> {
        self.sdk
            .run_skill("nutrition", "search_recipes", input)
            .await
    }
}
#[derive(Clone, Copy)]
pub struct OpenmatesSkills<'a> {
    sdk: &'a OpenMates,
}
impl OpenmatesSkills<'_> {
    pub async fn share_usecase(&self, input: Value) -> Result<Value> {
        self.sdk
            .run_skill("openmates", "share-usecase", input)
            .await
    }
    pub async fn get_docs(&self, input: Value) -> Result<Value> {
        self.sdk.run_skill("openmates", "get-docs", input).await
    }
}
#[derive(Clone, Copy)]
pub struct PdfSkills<'a> {
    sdk: &'a OpenMates,
}
impl PdfSkills<'_> {
    pub async fn read(&self, input: Value) -> Result<Value> {
        self.sdk.run_skill("pdf", "read", input).await
    }
    pub async fn search(&self, input: Value) -> Result<Value> {
        self.sdk.run_skill("pdf", "search", input).await
    }
    pub async fn view(&self, input: Value) -> Result<Value> {
        self.sdk.run_skill("pdf", "view", input).await
    }
}
#[derive(Clone, Copy)]
pub struct PlansSkills<'a> {
    sdk: &'a OpenMates,
}
impl PlansSkills<'_> {
    pub async fn create(&self, input: Value) -> Result<Value> {
        self.sdk.run_skill("plans", "create", input).await
    }
    pub async fn search(&self, input: Value) -> Result<Value> {
        self.sdk.run_skill("plans", "search", input).await
    }
}
#[derive(Clone, Copy)]
pub struct ProjectsSkills<'a> {
    sdk: &'a OpenMates,
}
impl ProjectsSkills<'_> {
    pub async fn create(&self, input: Value) -> Result<Value> {
        self.sdk.run_skill("projects", "create", input).await
    }
}
#[derive(Clone, Copy)]
pub struct ReminderSkills<'a> {
    sdk: &'a OpenMates,
}
impl ReminderSkills<'_> {
    pub async fn set_reminder(&self, input: Value) -> Result<Value> {
        self.sdk.run_skill("reminder", "set-reminder", input).await
    }
    pub async fn list_reminders(&self, input: Value) -> Result<Value> {
        self.sdk
            .run_skill("reminder", "list-reminders", input)
            .await
    }
    pub async fn cancel_reminder(&self, input: Value) -> Result<Value> {
        self.sdk
            .run_skill("reminder", "cancel-reminder", input)
            .await
    }
}
#[derive(Clone, Copy)]
pub struct ShoppingSkills<'a> {
    sdk: &'a OpenMates,
}
impl ShoppingSkills<'_> {
    pub async fn search_products(&self, input: Value) -> Result<Value> {
        self.sdk
            .run_skill("shopping", "search_products", input)
            .await
    }
}
#[derive(Clone, Copy)]
pub struct SocialMediaSkills<'a> {
    sdk: &'a OpenMates,
}
impl SocialMediaSkills<'_> {
    pub async fn get_posts(&self, input: Value) -> Result<Value> {
        self.sdk.run_skill("social_media", "get-posts", input).await
    }
    pub async fn search(&self, input: Value) -> Result<Value> {
        self.sdk.run_skill("social_media", "search", input).await
    }
}
#[derive(Clone, Copy)]
pub struct TasksSkills<'a> {
    sdk: &'a OpenMates,
}
impl TasksSkills<'_> {
    pub async fn create(&self, input: Value) -> Result<Value> {
        self.sdk.run_skill("tasks", "create", input).await
    }
    pub async fn search(&self, input: Value) -> Result<Value> {
        self.sdk.run_skill("tasks", "search", input).await
    }
}
#[derive(Clone, Copy)]
pub struct TravelSkills<'a> {
    sdk: &'a OpenMates,
}
impl TravelSkills<'_> {
    pub async fn search_connections(&self, input: Value) -> Result<Value> {
        self.sdk
            .run_skill("travel", "search_connections", input)
            .await
    }
    pub async fn search_stays(&self, input: Value) -> Result<Value> {
        self.sdk.run_skill("travel", "search_stays", input).await
    }
    pub async fn get_flight(&self, input: Value) -> Result<Value> {
        self.sdk.run_skill("travel", "get_flight", input).await
    }
}
#[derive(Clone, Copy)]
pub struct VideosSkills<'a> {
    sdk: &'a OpenMates,
}
impl VideosSkills<'_> {
    pub async fn generate(&self, input: Value) -> Result<Value> {
        self.sdk.run_skill("videos", "generate", input).await
    }
    pub async fn get_transcript(&self, input: Value) -> Result<Value> {
        self.sdk.run_skill("videos", "get_transcript", input).await
    }
    pub async fn search(&self, input: Value) -> Result<Value> {
        self.sdk.run_skill("videos", "search", input).await
    }
}
#[derive(Clone, Copy)]
pub struct WeatherSkills<'a> {
    sdk: &'a OpenMates,
}
impl WeatherSkills<'_> {
    pub async fn forecast(&self, input: Value) -> Result<Value> {
        self.sdk.run_skill("weather", "forecast", input).await
    }
    pub async fn rain_radar(&self, input: Value) -> Result<Value> {
        self.sdk.run_skill("weather", "rain_radar", input).await
    }
}
#[derive(Clone, Copy)]
pub struct WebSkills<'a> {
    sdk: &'a OpenMates,
}
impl WebSkills<'_> {
    pub async fn search(&self, input: Value) -> Result<Value> {
        self.sdk.run_skill("web", "search", input).await
    }
    pub async fn read(&self, input: Value) -> Result<Value> {
        self.sdk.run_skill("web", "read", input).await
    }
    pub async fn browse(&self, input: Value) -> Result<Value> {
        self.sdk.run_skill("web", "browse", input).await
    }
}
#[derive(Clone, Copy)]
pub struct WorkflowsSkills<'a> {
    sdk: &'a OpenMates,
}
impl WorkflowsSkills<'_> {
    pub async fn search(&self, input: Value) -> Result<Value> {
        self.sdk.run_skill("workflows", "search", input).await
    }
}
