import okhttp3.*;
import java.io.File;
import java.io.IOException;

public class DocumentIaClient {
    public static void main(String[] args) throws IOException {
        OkHttpClient client = new OkHttpClient().newBuilder().build();

        MultipartBody.Builder bodyBuilder = new MultipartBody.Builder()
            .setType(MultipartBody.FORM);

        FILE_CODE_PLACEHOLDER
        OVERRIDE_CODE_PLACEHOLDER
        METADATA_CODE_PLACEHOLDER

        RequestBody body = bodyBuilder.build();

        Request request = new Request.Builder()
            .url("URL_PLACEHOLDER")
            .post(body)
            .addHeader("X-API-KEY", "API_KEY_PLACEHOLDER")
            .addHeader("Accept", "application/json")
            .build();

        try (Response response = client.newCall(request).execute()) {
            if (!response.isSuccessful()) throw new IOException("Unexpected code " + response);
            System.out.println(response.body().string());
        }
    }
}
