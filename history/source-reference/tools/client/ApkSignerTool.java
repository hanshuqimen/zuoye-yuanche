import java.io.File;
import java.nio.file.Files;
import java.nio.file.Path;
import java.security.KeyFactory;
import java.security.PrivateKey;
import java.security.cert.CertificateFactory;
import java.security.cert.X509Certificate;
import java.security.spec.PKCS8EncodedKeySpec;
import java.util.List;

import com.android.apksig.ApkSigner;
import com.android.apksig.ApkVerifier;

/** Sign a locally adapted client with its owner's local key, then verify the output. */
public class ApkSignerTool {
    public static void main(String[] args) throws Exception {
        if (args.length != 4) throw new IllegalArgumentException("input.apk output.apk key.der cert.der");
        PrivateKey key = KeyFactory.getInstance("RSA").generatePrivate(
            new PKCS8EncodedKeySpec(Files.readAllBytes(Path.of(args[2]))));
        X509Certificate cert;
        try (var input = Files.newInputStream(Path.of(args[3]))) {
            cert = (X509Certificate) CertificateFactory.getInstance("X.509").generateCertificate(input);
        }
        var signer = new ApkSigner.SignerConfig.Builder("TerraLocal", key, List.of(cert)).build();
        new ApkSigner.Builder(List.of(signer)).setInputApk(new File(args[0]))
            .setOutputApk(new File(args[1])).setMinSdkVersion(24)
            .setV1SigningEnabled(true).setV2SigningEnabled(true).setV3SigningEnabled(true)
            .setV4SigningEnabled(false).setAlignmentPreserved(true).build().sign();
        var result = new ApkVerifier.Builder(new File(args[1])).setMinCheckedPlatformVersion(24)
            .build().verify();
        if (!result.isVerified()) throw new IllegalStateException("Signature verification failed: " + result.getErrors());
        System.out.println("Local APK signature verified");
    }
}
